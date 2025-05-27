# This is an automatically generated code sample.
# To make this code sample work in your Oracle Cloud tenancy,
# please replace the values for any parameters whose current values do not fit
# your use case (such as resource IDs, strings containing ‘EXAMPLE’ or ‘unique_id’, and
# boolean, number, and enum parameters with values not fitting your use case).

import oci

# Create a default config using DEFAULT profile in default location
# Refer to
# https://docs.cloud.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm#SDK_and_CLI_Configuration_File
# for more info
import wp_config

# Constants
compartment_id = wp_config.COMPARTMENT
config = oci.config.from_file(wp_config.CONFIG_FILE, wp_config.CONFIG_PROFILE)

#config["region"] = "us-ashburn-1"
config["region"] = "us-chicago-1"
#config["region"] = "sa-saopaulo-1"
#config["region"] = "uk-london-1"
#config["region"] = "ap-osaka-1"
#config["region"] = "eu-frankfurt-1"

# Service endpoint
endpoint = wp_config.ENDPOINT



# Initialize service client with default config file
generative_ai_client = oci.generative_ai.GenerativeAiClient(config, service_endpoint='ocid1.generativeaidedicatedaicluster.oc1.us-chicago-1.amaaaaaax3tnacaa6n54pcptrue3hsxuvablkqclzzbjetbqqjr3ylzvuo2q')


# Send the request to service, some parameters are not required, see API
# doc for more info
list_models_response = generative_ai_client.list_models(
    compartment_id=compartment_id,
    sort_order="ASC",
    sort_by="timeCreated")

# Get the data from response
#print(list_models_response.data)
for model in list_models_response.data.items:
    #print(f"{model.display_name}\n{model.id}\n    {model.lifecycle_state} - {model.lifecycle_details}: {model.capabilities}\n")
    print(f"{model.display_name}\n    State: {model.lifecycle_state} - {model.lifecycle_details}")
    print(f"    {model.id}")   
    print(f"    capabilities: {model.capabilities}")
    print(f"    created: {model.time_created} - deprecated: {model.time_deprecated} - on demand retired: {model.time_on_demand_retired}\n")

