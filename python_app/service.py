from flask import Flask, render_template, request, redirect, flash, jsonify, url_for, session, app
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime, timedelta
from html import unescape
from cache import CacheProviderFactory, LocalCacheProvider, RedisCacheProvider
import pytz
import oci
import secrets
import uuid
import logging
import sys
import json

def create_app(cmd, os_client, namespace):
    app = Flask(__name__)

    app.config['SECRET_KEY'] = str(secrets.token_hex)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(username):
        return User(username)
    
    # instantiate a logger
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    # instantiate a cache for handling authentication and sharing functionality
    # depending on arguments passed this will either be a local in-memory cache
    # or will connect to an OCI Cache Service with Redis instance
    cache_type = "cloud"
    hostname = "local"
    if cmd.use_local_cache:
        cache_type = "local"
    else:
        hostname = cmd.redis_url
    logging.info(f"Using cache type '{cache_type}' with hostname '{hostname}'")
    cache = CacheProviderFactory.get_cache_provider(cache_type, hostname)

    @app.route('/')
    @login_required
    def home():
        #
        # movie list is a dictionary of top level directories with an array of json objects of 
        # object paths and display names.  Example:
        # movie_list["folder1"] = [{name=foo1, display_name=bar1}, {name=foo2, display_name=bar2}]
        # movie_list["folder2"] = [{name=foo3, display_name=bar3}]
        #
        movie_list = {}

        #
        # exclude_list is a list that contains prefixes that we want to exclude from further file
        # processing.  this is because we want to represent a single entry for an HLS folder tied to the
        # the output.m3u8 playlist and not all of the underlying segment files
        exclude_list = []

        next_starts_with = None
        while True:
            try:
                response = os_client.list_objects(namespace, cmd.bucket, start=next_starts_with, prefix="", fields='size,timeCreated,timeModified,storageTier', retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)
                next_starts_with = response.data.next_start_with
                for object_file in response.data.objects:  
                    movie_list, exclude_list = add_object(movie_list, exclude_list, object_file)  
                if not next_starts_with:
                    break
            except Exception as e:
                flash('Error interacting with video repository')
                logging.debug("Error fetching object list: ")
                logging.debug(e)
                return render_template('home.html', sections=[], section_objects=[])

        keys = movie_list.keys()

        # get active tab if set in the request or populated in session
        active_tab = request.args.get("tab")
        if active_tab == None or active_tab not in keys:
            if "active_tab" in session.keys():
                active_tab = session["active_tab"]
            else:
                active_tab = list(keys)[0]
        session["active_tab"] = active_tab

        # render template with clickable list of movies
        return render_template('home.html', sections=keys, section_objects=movie_list[active_tab])

    @app.route('/movie')
    @login_required
    def detail():
        # handle output differently depending on whether movie is HLS or not
        is_hls = False

        # get name from request
        name = request.args.get("name")
        if name is None or len(name) < 5:
            flash('Missing or invalid video name')
            return redirect(url_for('home'))
        
        # strip folder name and suffix to build display name
        try:
            display_name = name.split("/",1)[1].rsplit(".", 1)[0]
            prefix = name.rsplit("/",1)[0] + "/"
            if ".hls" in display_name:
                is_hls = True
                display_name = display_name.split(".")[0]
        except:
            display_name = "Name not paresable"

        try:
            # remove expired PARs
            now = datetime.utcnow().replace(tzinfo=pytz.utc)
            list_par_response = os_client.list_preauthenticated_requests(namespace, cmd.bucket)
            for par in list_par_response.data:
                if par.time_expires < now:
                    os_client.delete_preauthenticated_request(namespace, cmd.bucket, par.id)

            # create two hour PAR 
            expiry_time = now + timedelta(hours=2)
            par_response = os_client.create_preauthenticated_request(
            namespace,
            cmd.bucket,
            create_preauthenticated_request_details=oci.object_storage.models.CreatePreauthenticatedRequestDetails(
                name=name + str(expiry_time),
                access_type="AnyObjectRead",
                time_expires=expiry_time,
                bucket_listing_action="Deny"
                ))
            
            par_url = cmd.os_endpoint + par_response.data.access_uri + name
        except Exception as e:
                flash('Error interacting with video repository')
                logging.debug("Error listing/creating PARs: ")
                logging.debug(e)
                return render_template('home.html', sections=[], section_objects=[])
        
        # set the encoding type depending on whether this is HLS or not
        if is_hls:
            encoding_type = "application/x-mpegURL"
        else:
            encoding_type = "video/mp4"

        # render the template
        return render_template('detail.html', par_url=par_url, video_name=display_name, full_name=name, encoding_type=encoding_type)
    
    @app.route('/shared')
    def shared():
        generic_error = "Unable to process.  Please contact whomever shared this link with you and request a new link."

        # get auth token from request
        auth_code = request.args.get("auth_code")
        if auth_code is None or len(auth_code) < 10:
            logging.error("Missing auth_code in share attempt")
            return render_template("auth_result.html", result=generic_error)
        
        # validate that the auth_code is valid
        name = cache.get_shared(auth_code)
        if name == None:
            logging.error("Invalid auth_code in share attempt")
            return render_template("auth_result.html", result=generic_error)
        
        # handle output differently depending on whether movie is HLS or not
        is_hls = False

        # strip folder name and suffix to build display name
        try:
            display_name = name.split("/",1)[1].rsplit(".", 1)[0]
            prefix = name.rsplit("/",1)[0] + "/"
            if ".hls" in display_name:
                is_hls = True
                display_name = display_name.split(".")[0]
        except:
            display_name = "Name not paresable"

        try:
            # remove expired PARs
            now = datetime.utcnow().replace(tzinfo=pytz.utc)
            list_par_response = os_client.list_preauthenticated_requests(namespace, cmd.bucket)
            for par in list_par_response.data:
                if par.time_expires < now:
                    os_client.delete_preauthenticated_request(namespace, cmd.bucket, par.id)

            # create two hour PAR 
            expiry_time = now + timedelta(hours=2)
            par_response = os_client.create_preauthenticated_request(
            namespace,
            cmd.bucket,
            create_preauthenticated_request_details=oci.object_storage.models.CreatePreauthenticatedRequestDetails(
                name=name + str(expiry_time),
                access_type="AnyObjectRead",
                time_expires=expiry_time,
                bucket_listing_action="Deny"
                ))
            
            par_url = cmd.os_endpoint + par_response.data.access_uri + name
        except Exception as e:
                flash('Error interacting with video repository')
                logging.debug("Error listing/creating PARs: ")
                logging.debug(e)
                return render_template('home.html', sections=[], section_objects=[])
        
        # set the encoding type depending on whether this is HLS or not
        if is_hls:
            encoding_type = "application/x-mpegURL"
        else:
            encoding_type = "video/mp4"

        # render the template
        return render_template('shared.html', par_url=par_url, video_name=display_name, encoding_type=encoding_type)
    
    @app.route('/share_url', methods=['GET', 'POST'])
    @login_required
    def share_url():
        auth_code = str(uuid.uuid4())
        name = unescape(request.json.get("name"))
        cache.set_shared(auth_code, name)
        target_url = request.url_root + url_for("shared") + "?auth_code=" + auth_code
        return jsonify(url=target_url)

    @app.route('/check_auth')
    def check_auth():
        is_authenticated = False
        session_id = request.args.get('session_id')
        logging.debug("check_auth:id: " + session_id)
        logging.debug("DICT: " + json.dumps(cache.get_authenticated_dict(), indent=2))
        if session_id:
            try:
                is_authenticated = cache.get_authenticated(session_id)
                logging.debug("check_auth:is_authenticated: " + str(is_authenticated))
                if is_authenticated:
                    login_user(User(cmd.username))
            except:
                is_authenticated = False
                logging.debug("check_auth:is_authenticated: " + str(is_authenticated))
        return jsonify(is_authenticated=is_authenticated)

    @app.route('/authenticate', methods=['GET'])
    def authenticate():
        session_id = request.args.get('session_id')
        return render_template('auth.html', session_id=session_id)
    
    @app.route('/authenticate', methods=['POST'])
    def authenticate_post():
        session_id = request.form.get('session_id')
        username = request.form.get('username')
        password = request.form.get('password')
        logging.debug("authenticate_post:" + str(session_id)+":"+username+":"+password)
        if username == cmd.username and password == cmd.password and session_id and cache.is_session_in_authenticated(session_id):
            cache.set_authenticated(session_id, True)
            logging.info("Success authenticating id: " + session_id)
            return render_template("auth_result.html", result="Success. Your viewing device should refresh momentarily. ")
        return render_template("auth_result.html", result="Unable to authenticate. Please check your head and try again.")

    @app.route('/login', methods=['GET'])
    def login():
        session_id = str(uuid.uuid4())
        cache.set_authenticated(session_id, False)
        target_url = request.url_root + url_for("authenticate") + "?session_id=" + session_id
        return render_template('login.html', target_url=target_url, session_id=session_id)

    @app.route('/login', methods=['POST'])
    def login_post():
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        if not(username == cmd.username and password == cmd.password):
            flash('Please check your login details and try again.')
            return redirect(url_for('login')) 

        login_user(User(username))
        return redirect(url_for('home'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('home'))
    
    # 
    # health check endpoint for load balancer and OCI Health Check Service
    #
    @app.route('/health')
    def health():
        return "i'm feeling good from my head to my shoes!"
    
    #
    # session timeout helper method
    #
    @app.before_first_request
    def set_session_duration():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(minutes=120)

    #
    # helper method to build the in-memory representation of the navigation
    #
    def add_object(movie_list, exclude_list, object_file):
        try:
            # decode directory and filename
            split_str = object_file.name.split("/", 1)
            dir = split_str[0]
            name = split_str[1]

            # if there is no file we just got a directory from os; ignore
            if len(name) < 1:
                return movie_list, exclude_list
            
            # check the name to see if it contains a directory in the exclude_list
            # if it does, it means we have already processed the playlist and this is just
            # a segment file which means that we should skip it
            if ".hls" in name:
                name_split = name.split(".")
                if name_split[0] in exclude_list:
                    return movie_list, exclude_list
                
            # check to see if directory exists in dictionary.  if not create
            if not dir in movie_list:
                movie_list[dir] = []

            if ".hls" in name:
                object_name = object_file.name + "output.m3u8"
                # get a display name without the extension
                display_name = name.rsplit(".", 1)[0]
                exclude_list.append(display_name)
            else:
                object_name = object_file.name
                # get a display name without the extension
                display_name = name.rsplit(".", 1)[0]
            
            # build video object and append to the right heading
            video = {"name": object_name, "display_name": display_name}
            movie_list[dir].append(video)
        except Exception as e:
            logging.error("add_object error: " + str(e))

        return movie_list, exclude_list
    
    return app

class User(UserMixin):
    def __init__(self, username):
        self.username = username
        self.id = username