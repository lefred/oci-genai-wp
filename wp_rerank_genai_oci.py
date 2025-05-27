import oci
import mysql.connector
import json

import wp_config

from unstructured.partition.html import partition_html
from unstructured.cleaners.core import clean
import bs4
from bs4 import BeautifulSoup

# Constants
compartment_id = wp_config.COMPARTMENT
config = oci.config.from_file(wp_config.CONFIG_FILE, wp_config.CONFIG_PROFILE)

# Service endpoint
endpoint = wp_config.ENDPOINT

config['region'] = wp_config.REGION

dedicated_rerank_endpoint = wp_config.DEDICATED_RERANK_ENDPOINT

generative_ai_inference_client = (
    oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        region="us-chicago-1",
        service_endpoint=endpoint,
        retry_strategy=oci.retry.NoneRetryStrategy(),
        timeout=(10, 240),
    )
)


def pdebug(msg=None):
    if wp_config.DEBUG and msg:
        print("DEBUG: {}".format(msg), flush=True)
        if wp_config.DEBUG_PAUSE:
            input("Press Enter to continue...")


myconfig = {
    "user": wp_config.DB_USER,
    "password": wp_config.DB_PASSWORD,
    "host": wp_config.DB_HOST,
    "port": wp_config.DB_PORT,
    "database": wp_config.DB_SCHEMA,
}


def connectMySQL(myconfig):
    cnx = mysql.connector.connect(**myconfig)
    return cnx


# Used to format response and return references
class Document:

    doc_id: int
    doc_text: str

    def __init__(self, id, text) -> None:

        self.doc_id = id
        self.doc_text = text

    def __str__(self):
        return f"doc_id:{self.doc_id},doc_text:{self.doc_text}"


# OCI-LLM: Used to generate embeddings for question(s)
def generate_embeddings_for_question(question_list):

    print("Performing Embeddings of the prompt...")
    embed_text_detail = oci.generative_ai_inference.models.EmbedTextDetails()
    embed_text_detail.inputs = question_list
    embed_text_detail.input_type = embed_text_detail.INPUT_TYPE_SEARCH_QUERY
    embed_text_detail.serving_mode = (
        oci.generative_ai_inference.models.OnDemandServingMode(
            model_id="cohere.embed-english-v3.0"
        )
    )
    embed_text_detail.compartment_id = compartment_id
    embed_text_response = generative_ai_inference_client.embed_text(embed_text_detail)
    return embed_text_response


# OCI-LLM: Used to prompt the LLM
def query_llm_with_prompt(documents, prompt):

    print("Generating the Answer...")
    my_documents = []
    for docs in documents:
        my_documents.append({"id": f"{docs.doc_id}", "text": docs.doc_text})

    chat_detail = oci.generative_ai_inference.models.ChatDetails()

    chat_request = oci.generative_ai_inference.models.CohereChatRequest()
    chat_request.documents = my_documents
    chat_request.message = prompt
    chat_request.max_tokens = 600
    chat_request.temperature = 1
    chat_request.frequency_penalty = 0
    chat_request.top_p = 0.75
    chat_request.top_k = 0

    chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(
        model_id=wp_config.LLM_MODEL_ID
    )
    chat_detail.chat_request = chat_request
    chat_detail.compartment_id = compartment_id
    chat_response = generative_ai_inference_client.chat(chat_detail)

    return vars(chat_response)


# Find relevant records from HeatWave using Dot Product similarity.
def search_data(cursor, query_vec, list_dict_docs):

    print("Performing Vector Search Similarity...")
    myvectorStr = ",".join(str(item) for item in query_vec)
    myvectorStr = "[" + myvectorStr + "]"

    relevant_docs = []
    mydata = myvectorStr
    cursor.execute(
        """
        select distinct wp_post_id from (
          select id, wp_post_id, distance from
            (select id, wp_post_id,
                    DISTANCE(string_to_vector(%s), vec, 'COSINE') distance
             from {}.wp_embeddings
             order by distance limit 100) a
             where distance < 1 order by distance) b limit 50 

    """.format(
            wp_config.DB_SCHEMA
        ),
        [myvectorStr],
    )

    for row in cursor:
        id = row[0]
        result_post = []
        with connectMySQL(myconfig) as db2:
            cursor2 = db2.cursor()
            cursor2.execute(
                "SELECT post_content from wp_posts where id = {} ".format(id)
            )
            result_post = cursor2.fetchone()

        soup = BeautifulSoup(result_post[0], "html.parser")
        for element in soup(
            text=lambda text: isinstance(text, bs4.element.ProcessingInstruction)
        ):
            element.extract()
        content_text = soup.get_text()

        if len(content_text) > 0:
            content = clean(content_text, extra_whitespace=True)

        temp_dict = {id: content}
        list_dict_docs.append(temp_dict)
        doc = Document(id, content)
        # print(doc)
        relevant_docs.append(doc)

    return relevant_docs


# Perform RAG
def answer_user_question(query):

    question_list = []
    question_list.append(query)

    embed_text_response = generate_embeddings_for_question(question_list)

    question_vector = embed_text_response.data.embeddings[0]

    with connectMySQL(myconfig) as db:
        cursor = db.cursor()
        list_dict_docs = []
        # query vector db to search relevant records
        similar_docs = search_data(cursor, question_vector, list_dict_docs)

        # prepare documents for the prompt
        context_documents = []
        relevant_doc_ids = []
        similar_docs_subset = []

        rerank_docs = []
        for docs in similar_docs:
            content = docs.doc_text
            rerank_docs.append(content)
        
        if len(rerank_docs) > 1:
            print("Performing Reranking...")
            rerank_details = oci.generative_ai_inference.models.RerankTextDetails(
                input=query,
                compartment_id = compartment_id,
                documents=rerank_docs,
                serving_mode = oci.generative_ai_inference.models.DedicatedServingMode(
                    endpoint_id = dedicated_rerank_endpoint 
                    ),
                top_n=5,
                is_echo=True
            )
            response = generative_ai_inference_client.rerank_text(rerank_details)
            #print(response.data)
        else:
            print("No corresponding document found, using GenAI...")

        myresult = response.data 

        rerank_docs_subset = []
        for rerank_result in myresult.document_ranks:
            indice = int(rerank_result.index)
            rerank_docs_subset.append(similar_docs[indice])

        prompt_template = """
        {question} \n
        Answer the question based on the text provided and also return the relevant document numbers where you found the answer. If the text doesn't contain the answer, reply that the answer is not available.
        """

        prompt = prompt_template.format(question=query)

        llm_response_result = query_llm_with_prompt(rerank_docs_subset, prompt)
        response = {}
        response["message"] = query
        response["text"] = llm_response_result
        response["documents"] = [
            {"id": doc.doc_id, "snippet": doc.doc_text} for doc in similar_docs_subset
        ]

        return response


# Main Function

cnx = connectMySQL(myconfig)
if cnx.is_connected():
    cursor = cnx.cursor()
    cursor.execute("SELECT @@version, @@version_comment")
    results = cursor.fetchone()

    print("You are now connected to {} {}".format(results[1], results[0]))

    question = input("What is your question? ")
    myanswer = answer_user_question(question)

    # print(myanswer['text']['data'])

    print(myanswer["text"]["data"].chat_response.text)
    if myanswer["text"]["data"].chat_response.documents is not None:
        for el in myanswer["text"]["data"].chat_response.documents:
            cursor.execute("SELECT post_title from wp_posts where id = {}".format(el["id"]))
            result = cursor.fetchone()
            print(" - [{}]: {}".format(el["id"], result[0]))
    cnx.close()
