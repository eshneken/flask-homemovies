import oci
import sys
import base64
import argparse

if __name__ == "__main__":
    # get variables from parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance_principal', action='store_true', default=False, dest='use_instance_principal', help='Use Instance Principals for Authentication')
    parser.add_argument('--resource_principal', action='store_true', default=False, dest='use_resource_principal', help='Use Resource Principals for Authentication')
    parser.add_argument('--secret', default="", dest='secret', help='OCID of compartment with secrets vault')
    parser.add_argument('--bucket', default="", dest='bucket', help='Bucket Name')
    parser.add_argument('--os_endpoint', default="https://objectstorage.us-ashburn-1.oraclecloud.com", dest='os_endpoint', help='Object Storage Endpoint')
    parser.add_argument('--username', default="", dest='username', help='Username')
    parser.add_argument('--password', default="", dest='password', help='Password')
    cmd = parser.parse_args()

    # exit if required parameters and not specified
    if len(sys.argv) < 1:
        parser.print_help()
        raise SystemExit

    # build object storage client whether config file based on instance principal
    if cmd.use_instance_principal:
        try:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            config = {'region': signer.region, 'tenancy': signer.tenancy_id}

        except Exception as e:
            print(e)
            print("Error obtaining instance principal configuration, aborting")
            raise SystemExit
    elif cmd.use_resource_principal:
        try:
            signer = oci.auth.signers.get_resource_principals_signer()
            config = {'region': signer.region, 'tenancy': signer.tenancy_id}

        except Exception as e:
            print(e)
            print("Error obtaining resource principal configuration, aborting")
            raise SystemExit
    else:
        try:
            config = oci.config.from_file("~/.oci/config","DEFAULT")
            signer = oci.signer.Signer(
                    tenancy=config["tenancy"],
                    user=config["user"],
                    fingerprint=config["fingerprint"],
                    private_key_file_location=config.get("key_file"),
                    pass_phrase=oci.config.get_config_value_or_default(config, "pass_phrase"),
                    private_key_content=config.get("key_content")
                )
        except Exception as e:
            print(e)
            print("Error building config for SDK config, aborting")
            raise SystemExit

    # If --secret passed in derive username, password, bucket from secret
    if cmd.secret:
        try:
            vault_client = oci.vault.VaultsClient(config=config, signer=signer)
            secret_client = oci.secrets.SecretsClient(config=config, signer=signer)

            secrets_list = vault_client.list_secrets(cmd.secret)
            for secret in secrets_list.data:
                response = secret_client.get_secret_bundle(secret.id)
                base64_Secret_content = response.data.secret_bundle_content.content
                base64_secret_bytes = base64_Secret_content.encode('ascii')
                base64_message_bytes = base64.b64decode(base64_secret_bytes)
                secret_content = base64_message_bytes.decode('ascii')
                match secret.secret_name:
                    case "username":
                        cmd.username = secret_content
                    case "password":
                        cmd.password = secret_content
                    case "bucket":
                        cmd.bucket = secret_content
        except Exception as e:
            print(e)
            print("Error building retrieving vaults and secrets, aborting")
            raise SystemExit

    # build the object storage client   
    os_client = oci.object_storage.ObjectStorageClient(config, signer=signer)
    namespace = os_client.get_namespace(retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY).data

    if not (cmd.username and cmd.password):
        print("Username and password parameters are required. Pass in as arguments or dervie from a secret.\n")
        parser.print_help()
        raise SystemExit

    if not cmd.bucket:
        print("Bucket parameter is required.\n")
        parser.print_help()
        raise SystemExit

    # create and run the flask app
    app = create_app(cmd, os_client, namespace)
    app.run(host="0.0.0.0", port=5000)



