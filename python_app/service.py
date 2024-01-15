from flask import Flask, render_template, request, redirect, flash, jsonify, url_for, session, app
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin
from datetime import datetime, timedelta
import pytz
import oci
import secrets
import uuid
import logging
import sys

def create_app(cmd, os_client, namespace):
    app = Flask(__name__)

    app.config['SECRET_KEY'] = str(secrets.token_hex)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(username):
        return User(username)
    
    authenticated = {}
    
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    @app.route('/')
    @login_required
    def home():
        # collect objects in bucket
        movie_list = {}
        next_starts_with = None
        while True:
            try:
                response = os_client.list_objects(namespace, cmd.bucket, start=next_starts_with, prefix="", fields='size,timeCreated,timeModified,storageTier', retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)
                next_starts_with = response.data.next_start_with
                for object_file in response.data.objects:  
                    movie_list = add_object(movie_list, object_file)  
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
        # get name from request
        name = request.args.get("name")
        if name is None or len(name) < 5:
            flash('Missing or invalid video name')
            return redirect(url_for('home'))
        
        # strip folder name and suffix to build display name
        try:
            display_name = name.split("/",1)[1].rsplit(".", 1)[0]
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
                access_type="ObjectRead",
                time_expires=expiry_time,
                bucket_listing_action="Deny",
                object_name=name))
            
            par_url = cmd.os_endpoint + par_response.data.access_uri
        except Exception as e:
                flash('Error interacting with video repository')
                logging.debug("Error listing/creating PARs: ")
                logging.debug(e)
                return render_template('home.html', sections=[], section_objects=[])
        
        return render_template('detail.html', par_url=par_url, video_name=display_name)
    
    @app.route('/check_auth')
    def check_auth():
        is_authenticated = False
        session_id = request.args.get('session_id')
        logging.debug("check_auth:id: " + session_id)
        if session_id:
            try:
                is_authenticated = authenticated[session_id]
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
        logging.debug("authenticate_post:" + str(session_id)+":"+username+":"+"password")
        if username == cmd.username and password == cmd.password and session_id and session_id in authenticated:
            authenticated[session_id]=True
            logging.info("Success authenticating id: " + session_id)
            return render_template("auth_result.html", result="Success. Your viewing device should refresh momentarily. ")
        return render_template("auth_result.html", result="Unable to authenticate. Please check your head and try again.")

    @app.route('/login', methods=['GET'])
    def login():
        session_id = str(uuid.uuid4())
        authenticated[session_id]=False
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
    
    @app.route('/health')
    def health():
        return "i'm feeling good from my head to my shoes!"
    
    @app.before_first_request
    def set_session_duration():
        session.permanent = True
        app.permanent_session_lifetime = timedelta(minutes=120)

    def add_object(movie_list, object_file):
        try:
            # decode directory and filename
            split_str = object_file.name.split("/", 1)
            dir = split_str[0]
            name = split_str[1]

            # if there is no file we just got a directory from os; ignore
            if len(name) < 1:
                return movie_list
            
            # check to see if directory exists in dictionary.  if not create
            if not dir in movie_list:
                movie_list[dir] = []

            # get a display name without the file type
            display_name = name.rsplit(".", 1)[0]
            
            # build video object and append to the right heading
            video = {"name": object_file.name, "display_name": display_name}
            movie_list[dir].append(video)
        except Exception as e:
            logging.error("add_object error: " + str(e))

        return movie_list
    
    return app

class User(UserMixin):
    def __init__(self, username):
        self.username = username
        self.id = username