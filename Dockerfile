#
# docker build -t flask-homemovies .
#
# Build with:  docker build -t flask-homemovies .
# Run with container locally: docker run -p 5000:5000 --mount type=bind,source=$HOME/.oci,target=/root/.oci --mount type=bind,source=$HOME/Keys,target=$HOME/Keys flask-homemovies --bucket $bname --username $uname --password $pwd
# Run with container in OCI: docker run -p 5000:5000 flask-homemovies --bucket $bname --username $uname --password $pwd --instance_principal
# Run with local volume:  docker run -p 5000:5000 -w /app -v "$(pwd):/app" flask-homemovies
#
FROM python:3.11
EXPOSE 5000
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . /app
ENTRYPOINT ["python3", "app.py"]
