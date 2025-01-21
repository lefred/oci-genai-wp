import oci
import mysql.connector
import time
import wp_config
from unstructured.partition.html import partition_html
from unstructured.cleaners.core import clean
from bs4 import BeautifulSoup
import bs4


# Constants
compartment_id = wp_config.COMPARTMENT
config = oci.config.from_file(wp_config.CONFIG_FILE, wp_config.CONFIG_PROFILE)

# Service endpoint
endpoint = wp_config.ENDPOINT

generative_ai_inference_client = (
    oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        service_endpoint=endpoint,
        retry_strategy=oci.retry.NoneRetryStrategy(),
        timeout=(10, 240),
    )
)

myconfig = {
    "user": wp_config.DB_USER,
    "password": wp_config.DB_PASSWORD,
    "host": wp_config.DB_HOST,
    "port": wp_config.DB_PORT,
    "database": wp_config.DB_SCHEMA,
}


def pdebug(msg=None):
    if wp_config.DEBUG and msg:
        print("DEBUG: {}".format(msg), flush=True)
        if wp_config.DEBUG_PAUSE:
            input("Press Enter to continue...")


def connectMySQL(myconfig):
    cnx = mysql.connector.connect(**myconfig)
    return cnx


# Main Function

cnx = connectMySQL(myconfig)
if cnx.is_connected():
    cursor = cnx.cursor()
    cursor.execute("SELECT @@version, @@version_comment")
    results = cursor.fetchone()

    print("You are now connected to {} {}".format(results[1], results[0]))
    print("Starting Embeddings....")

    # generate embedding for column post_content
    cursor.execute("SELECT ID, post_content from wp_posts WHERE post_status='publish'")
    results = cursor.fetchall()

    for row in results:
        pdebug(f"We are now at wp_post_id: {row[0]}")
        # time.sleep(0.5)
        print(".", flush=True, end="")
        inputs = []
        content = row[1]
        pdebug(content)
        content_text = BeautifulSoup(content, "html.parser")
        for pi in content_text.find_all(
            string=lambda text: isinstance(text, bs4.element.ProcessingInstruction)
        ):
            pi.extract()

        clean_html = str(content_text)
        # content_text = partition_html(text=content_text.get_text())
        try:
            content_text = partition_html(text=clean_html)
            for content_text_el in content_text:
                content = clean(content_text_el.text, extra_whitespace=True)
                inputs.append(content)

        except Exception as e:
            print(f"Error with wp_post_id: {row[0]} !")

        if len(inputs) > 1:
            for input_block in range(0, len(inputs), 96):
                block = inputs[input_block : input_block + 96]
                pdebug(block)
                embed_text_detail = (
                    oci.generative_ai_inference.models.EmbedTextDetails()
                )
                embed_text_detail.inputs = block
                embed_text_detail.truncate = embed_text_detail.TRUNCATE_END
                embed_text_detail.serving_mode = (
                    oci.generative_ai_inference.models.OnDemandServingMode(
                        model_id="cohere.embed-english-v3.0"
                    )
                )
                embed_text_detail.compartment_id = compartment_id
                embed_text_detail.input_type = (
                    embed_text_detail.INPUT_TYPE_SEARCH_DOCUMENT
                )

            try:
                embed_text_response = generative_ai_inference_client.embed_text(
                    embed_text_detail
                )
            except Exception as e:
                print("Error while creating embeddings ", e)
                embeddings = []
            else:
                embeddings = embed_text_response.data.embeddings
                insert_stmt = (
                    "INSERT INTO wp_embeddings(vec, wp_post_id) "
                    "VALUES (string_to_vector(%s), %s)"
                )

                for emb in embeddings:
                    myvectorStr = ",".join(str(item) for item in list(emb))
                    myvectorStr = "[" + myvectorStr + "]"
                    data = (myvectorStr, row[0])
                    cursor.execute(insert_stmt, data)
        cnx.commit()


cnx.close()
print("\nDone with Embeddings.")
