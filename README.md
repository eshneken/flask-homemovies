# flask-homemovies
Flask application to serve video files from OCI object storage in a secure web interface

# Usage
usage: 

    app.py [-h] [--instance_principal] [--resource_principal] [--secret SECRET] [--bucket BUCKET] [--os_endpoint OS_ENDPOINT] [--username USERNAME] [--password PASSWORD]

    options:
    -h, --help                show this help message and exit
    --local_cache             Use local (in-process) cache instead of OCI Cache Service with Redis
    --instance_principal      Use Instance Principals for Authentication
    --resource_principal      Use Resource Principals for Authentication
    --secret SECRET           OCID of compartment with secrets vault
    --bucket BUCKET           Bucket Name
    --redis-url REDIS_URL     OCI Cache Service with Redis Endpoint
    --os_endpoint OS_ENDPOINT Object Storage Endpoint
    --username USERNAME       Username
    --password PASSWORD       Password

1. The object storage endpoint defaults to Ashburn, otherwise select an [endpoint from the list](https://docs.oracle.com/en-us/iaas/api/#/en/objectstorage/20160918/). 
1. Use instance principal auth for running on an OCI compute instance OR resource principal auth for running in an OCI container instance OR pass neither parameter which means we assume an OCI config file in ~/.oci
1. Bucket refers to the bucketname with foldered videos. 
1. Username and Password are the challenge credentials for the Flask app
1. Either bucket, username, and password need to be passed in or the secret flag must be passed with the OCID of a compartment that contains an OCI Secret Vault that holds those three secrets

# Preparing the local environment
1. cd python_app (enter the code working directory)
1. python3 -m venv ./.venv  (prepare the Python virtual environment)
1. source ./.venv/bin/activate (activate the virtual environment)
1. pip install -r requirements.txt (install all packages in virtual environment)
1. docker build -t flask-homemovies .  (optionally build if you plan to run with docker)

# Running locally
1. Make sure you have an OCI config file at [~/.oci/config](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliconfigure.htm).  
2. Most likely you will pass --bucket, --username, --password or alternatively can simply use --secret
3. Debugging can be done in VSCode, sample launch.json.template can be modified and renamed launch.json
4. To run locally with docker:  docker run --mount type=bind,source=$HOME/.oci,target=/root/.oci flask-homemovies --bucket $bname --username $uname --password $pwd

# Pushing to OCIR
1. Create new private registry with name: hm/flask-homemovies in the hm compartment
1. Make sure to cross-compile for AMD targets if you plan to run in OC1.  Your image build command should look more like this:
```
docker build -t flask-homemovies . --platform linux/amd64
```
1. docker login ocir.us-ashburn-1.oci.oraclecloud.com -u $username -p $auth_token (login to remote OCIR registry)
1. docker tag flask-homemovies:latest ocir.us-ashburn-1.oci.oraclecloud.com/$os_namespace/hm/flask-homemovies (tag local image for push)
2. docker push ocir.us-ashburn-1.oci.oraclecloud.com/$os_namespace/hm/flask-homemovies:latest (push image to OCIR)

# Running in OCI on compute instance
1. Make sure dynamic groups and policies have been defined
1. docker run flask-homemovies --bucket $bname --username $uname --password $pwd --instance_principal (run in docker with instance principal permissions)

# Object Storage Configuration

All of the movies are served from OCI object storage.  Structuring the bucket following conventions described here is critical to the code functioning properly.

1. The bucket should have 1 level of directories which will serve the top level navigation.  There can be only one level of navigation.
1. Individual files should be put in these buckets with the appropriate extensions (e.g. .mp4, .avi, .mov)
1. For streaming 4K using adaptive bitrate you will need to generate an HLS directory consisting of a playlist (output.m3u8) and multiple segment files (output000.ts, output001.ts, etc).
1. An HLS directory must be uploaded to object storage into an object storage folder and the title of the folder must end with .hls
1. The HLS playlist file must be named output.m3u8.  Although segments can be named something else since they are referenced in the playlist, it is recommended to follow the HLS generation sample command below.

Here is a sample of what this might look like:

![folder structure](folder_structure.png)

# HLS Directory Generation

Converting a 4K mp4 to HLS can be accomplished using the [FFMPEG](https://ffmpeg.org) tool.  Here is a sample command used to generate the HLS output:

    ffmpeg -i input.mp4 \
        -vf "scale=-2:2160" \  # Video filter to scale the video to a height of 2160 pixels (4K resolution)
        -c:v libx264 \          # Video codec to encode the video using H.264 codec
        -x264opts "keyint=24:min-keyint=24:no-scenecut" \  # Options for the x264 encoder
        -b:v 8000k \            # Target video bitrate (8 Mbps)
        -maxrate 10000k \       # Maximum video bitrate (10 Mbps)
        -bufsize 20000k \       # Buffer size for the video bitrate control
        -c:a aac \              # Audio codec to encode the audio using AAC codec
        -ac 2 \                 # Set the number of audio channels to stereo
        -b:a 128k \             # Target audio bitrate (128 kbps)
        -hls_time 4 \           # Duration of each HLS segment (4 seconds)
        -hls_playlist_type vod \# HLS playlist type (Video On Demand)
        output.m3u8             # Output HLS playlist file

# Uploading HLS Directory to Object Storage

An HLS directory may contain thousands of files.  The easiest way to upload it and map it to the proper folder (prefix) is to use the OCI CLI's bulk-upload command.

For example, if we follow the example above and assume the object storage namespace is 'MyNamespace' the command would look like this:

    oci os object bulk-upload -ns MyNamespace -bn MyMovies --src-dir . --prefix "2022.hls/"

You will need to replace MyNamespace, MyMovies, and the directory name (2022.hls) with your own values.  Make sure the folder is already created inside OCI and you are running this command from the folder with the playlist and segments.

# Other tenancy setup
1. VCN Setup
    1. VCN Wizard with Internet connectivity
    1. Name: hm-vcn, CIDR: 10.0.0.0/24
    1. Public subnet:  10.0.0.0/25
    1. Private subnet: 10.0.0.128/25
    1. After VCN created, add ingress rule to public security list for 0.0.0.0/0 access to TCP/80 & TCP/443
    1. Add ingress rule to private security list for 10.0.0.0/25 to allow TCP/5000.  This will allow the LB in the public subnet to access the container on port 5000 in the private subnet/
1. OCI Cache Setup
    1. Name hm-redis-cluster
    1. Non-sharded, 2 nodes, 2GB RAM each
    1. Select hm-vcn and the private subnet
1. Vault Setup
    1. Create vault 'hm-vault'. 
    1. Create master encryption key 'hm-master-key' with software protection (to save costs)
    1. Create secrets with manual generation and no rotation off the master encryption key
        1. redis-url:  primary redis caching endpoint (i.e. amabxdvnfaafczpvajtbq-p.redis.us-ashburn-1.oci.oraclecloud.com)	
        1. bucket:  object storage bucket name (i.e. eshneken-hm)	
        1. username: website username (i.e. moviewatcher)
        1. password: website password (i.e. .....)
1. IAM Setup
    1. Dynamic Group Creation
        Create hm-container-instances-dg rule with ANY selected (two rules)
        ```
        ALL {resource.type='computecontainerinstance'}	
        ALL {instance.compartment.id='$ocid_of_hm_compartment'}
        ```
    1. Policy Setup
        Create container-instances-policy in hm compartment
        ```
        Allow dynamic-group hm-container-instances-dg to use object-family in compartment hm
        Allow dynamic-group hm-container-instances-dg to use object-family in compartment hm
        Allow dynamic-group hm-container-instances-dg to manage buckets in compartment hm where ANY { request.permission = 'PAR_MANAGE'}	 
        Allow dynamic-group hm-container-instances-dg to manage buckets in compartment hm where ANY { request.permission = 'PAR_MANAGE'}
        Allow dynamic-group hm-container-instances-dg to manage leaf-certificate-family in compartment hm
        Allow dynamic-group hm-container-instances-dg to manage leaf-certificate-family in compartment hm
        Allow dynamic-group hm-container-instances-dg to read secret-family in compartment hm
        Allow dynamic-group hm-container-instances-dg to read repos in compartment hm
        ```

1. Container Instance
    1. Create a container instance with name: hm-private-subnet-use-vault, shape: CI.Standard.E4.Flex, subnet: private subnet
    1. container name: hm-container and select the image that uploaded to OCIR.  Don't worry about permissions, we have a policy that allows for repos to be read in the compartment.
    1. Select "advanced options" and "command arguments" and add
    ```
    --resource_principal,--secret=$ocid_of_hm_compartment
    ```
    1. Record the private IP of the container instance.  You will need this to set the load balancer's backend address.

1. Load Balancer
    1. Create a Layer7 application load balancer with:
        1. name: hm-lbaas
        1. visibility: public
        1. ip address: ephemeral
        1. bandwidth: 10 to 200 Mbps
        1. network:  select your vcn with the public subnet
        1. lb policy: weighted round robin
        1. backend servers: don't select any
        1. health check:  protocol: HTTP, port: 5000, URI: /health
        1. Configure HTTPS listener. Select LB managed certificate.  Upload server.crt, rootCA.crt, and server.key generated by running generate-ssl.sh script in this repository.  Script taken from: https://devopscube.com/create-self-signed-certificates-openssl/
        1. Enable error logging
        1. Wait until the LBaaS is created to continute configuring it
    1. Configure backend set
        1. Go to LB->backend sets->Backends and add a backend with IP address.
        1. Specify the IP address of the container instance previously created and set the port to 5000
        1. You previously enabled TCP/5000 ingress into the private subnet.  Double check if necessary.
        1. Double check that the health check is correct.
    1. Configure HTTP -> HTTPS redirect
        1. Create a backend set called "empty-set" with no targets
        1. Create a rule set called http_to_https_redirect.  Add a URL redirect rule with:
            1. Source path: /
            1. Match type: Force longest prefix match
            1. Redirect protocol: https
            1. Redirect host: {host}
            1. Redirect port: 443
            1. Redirect path: /{path}
            1. Redirect query: ?{query}
            1. Response code: 302 1. Found
        1. Create an HTTP listener (protocol HTTP, port 80) targeting the empty-set backend set.  Select the http_to_https_redirect rule set.
    1. If self-signed certificates are not desirable, it is possible to use LetsEncrypt to integrate a public certificate solution:  https://blog.johnnybytes.com/how-to-use-and-renew-ssl-certificates-on-oracle-cloud-oci-load-balancers-3c3b4c72c136

1. CI/CD with GitHub Actions

    The .github/workflows/main.yml file contains the simple build and deploy pipeline for this application.  Any push to the main branch (or manual run from GitHub Actions) will trigger a docker build, push into OCIR, and a restart of the container instance that will result in pulling the latest docker image.

    The following GitHub Actions secrets must be set by going to Settings->Secrets and variables->Repository Secrets:

    * OCI_AUTH_TOKEN
    * OCI_CLI_FINGERPRINT
    * OCI_CLI_KEY_CONTENT
    * OCI_CLI_REGION
    * OCI_CLI_TENANCY
    * OCI_CLI_USER
    * OCI_COMPARTMENT_OCID
    * OCI_CONTAINER_INSTANCE_OCID






