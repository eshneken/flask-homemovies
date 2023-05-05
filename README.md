# flask-homemovies
Flask application to serve video files from OCI object storage in a secure web interface

# Usage
usage: 

    app.py [-h] [--instance_principal] [--resource_principal] [--secret SECRET] [--bucket BUCKET] [--os_endpoint OS_ENDPOINT] [--username USERNAME] [--password PASSWORD]

    options:
    -h, --help                show this help message and exit
    --instance_principal      Use Instance Principals for Authentication
    --resource_principal      Use Resource Principals for Authentication
    --secret SECRET           OCID of compartment with secrets vault
    --bucket BUCKET           Bucket Name
    --os_endpoint OS_ENDPOINT Object Storage Endpoint
    --username USERNAME       Username
    --password PASSWORD       Password

1. The object storage endpoint defaults to Ashburn, otherwise select an [endpoint from the list](https://docs.oracle.com/en-us/iaas/api/#/en/objectstorage/20160918/). 
1. Use instance principal auth for running on an OCI compute instance OR resource principal auth for running in an OCI container instance OR pass neither parameter which means we assume an OCI config file in ~/.oci
1. Bucket refers to the bucketname with foldered videos. 
1. Username and Password are the challenge credentials for the Flask app
1. Either bucket, username, and password need to be passed in or the secret flag must be passed with the OCID of a compartment that contains an OCI Secret Vault that holds those three secrets

# Preparing the local environment
1. python3 -m venv ./.venv  (prepare the Python virtual environment)
1. source ./.venv/bin/activate (activate the virtual environment)
1. pip install -r requirements.txt (install all packages in virtual environment)
1. docker build -t flask-homemovies . (optionally build if you plan to run with docker)

# Running locally
1. Make sure you have an OCI config file at [~/.ici/config](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliconfigure.htm).  
2. Most likely you will pass --bucket, --username, --password or alternatively can simply use --secret
3. Debugging can be done in VSCode, sample launch.json.template can be modified and renamed launch.json
4. To run locally with docker:  docker run --mount type=bind,source=$HOME/.oci,target=/root/.oci flask-homemovies --bucket $bname --username $uname --password $pwd

# Pushing to OCIR
1. docker login (login to remote OCIR registry)
1. docker tag flask-homemovies:latest $region_code.ocir.io/$os_namespace/hm/flask-homemovies (tag local image for push)
2. docker push $region_code.ocir.io/$os_namespace/hm/flask-homemovies:latest (push image to OCIR)

# Running in OCI on compute instance
1. Make sure dynamic groups and policies have been defined
1. docker run flask-homemovies --bucket $bname --username $uname --password $pwd --instance_principal (run in docker with instance principal permissions)

