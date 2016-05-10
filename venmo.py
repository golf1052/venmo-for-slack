﻿from flask import Flask, request, send_from_directory
import ConfigParser
import requests
import datetime
import pytz
import sys
import json
from pymongo import MongoClient

app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    if 'code' in request.args:
        return send_from_directory('', 'code.html')
    else:
        return send_from_directory('', 'index.html')

@app.route('/js/<path:filename>', methods=['GET'])
def serve_js(filename):
    return send_from_directory('js', filename)

@app.route('/', methods=['POST'])
def process():
    credentials = ConfigParser.ConfigParser()
    credentials.read('credentials.ini')
    user_id = request.values.get('user_id')
    message = request.values.get('text')
    response_url = request.values.get('response_url')
    token = request.values.get('token')
    verification_token = credentials.get('Slack', 'token')
    if (token != verification_token):
        return str('Team verification token mismatch')
    split_message = message.split()
    if (len(split_message) > 0):
        if (split_message[0].lower() == 'code'):
            if (len(split_message) == 1):
                help(response_url)
            else:
                complete_auth(split_message[1], user_id, response_url)
                return str('')
    access_token = get_access_token(user_id, response_url)
    if (access_token != None):
        venmo_id = _get_venmo_id(access_token)
        if (venmo_id != ''):
            parse_message('venmo ' + message, access_token, user_id, venmo_id, response_url)
    return str('')

@app.route('/webhook', methods=['GET'])
def webhook_get():
    venmo_challenge = request.args.get('venmo_challenge')
    return str(venmo_challenge)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    db = connect_to_mongo()
    users = list(db.users.find())
    user = None
    message = ''
    if (data['type'] == 'payment.created'):
        for user in users:
            if (user['venmo']['id'] == data['data']['target']['user']['id']):
                user = user['_id']
                break
        if user is None:
            return str('')
        message += data['data']['actor']['display_name'] + ' '
        if (data['data']['action'] == 'pay'):
            message += 'paid you '
        elif (data['data']['action'] == 'charge'):
            message += 'charged you '
        message += '$' + str(data['data']['amount']) + ' '
        message += 'for ' + data['data']['note']
        if (data['data']['action'] == 'charge'):
            message += ' | ID: ' + data['data']['id']
        send_slack_message(message, user)
        if (data['data']['action'] == 'charge'):
            accept_command = '/venmo complete accept ' + data['data']['id']
            send_slack_message(accept_command, user)
    elif (data['type'] == 'payment.updated'):
        if (data['data']['target']['type'] != 'user'):
            return str('')
        for user in users:
            if (user['venmo']['id'] == data['data']['actor']['id']):
                user = user['_id']
                break
        if user is None:
            return str('')
        message += data['data']['target']['user']['display_name'] + ' '
        if (data['data']['status'] == 'settled'):
            message += 'accepted your '
        elif (data['data']['status'] == 'cancelled'):
            message += 'rejected your '
        message += '$' + str(data['data']['amount']) + ' charge '
        message += 'for ' + data['data']['note']
        send_slack_message(message, user)
    return str('')

def send_slack_message(message, channel):
    credentials = ConfigParser.ConfigParser()
    credentials.read('credentials.ini')
    bot_token = credentials.get('Slack', 'bot-token')
    o = {}
    o['token'] = bot_token
    o['channel'] = channel
    o['text'] = message
    o['username'] = 'Venmo'
    o['icon_url'] = 'https://s3-us-west-2.amazonaws.com/slack-files2/avatars/2015-11-10/14228813844_49fae5f9cad227c8c1b5_72.jpg'
    response = requests.post('https://slack.com/api/chat.postMessage', data=o)

def respond(message, response_url):
    o = {}
    o['text'] = message
    response = requests.post(response_url, json=o)

# Connects to mongo and returns a MongoClient
def connect_to_mongo():
    credentials = ConfigParser.ConfigParser()
    credentials.read("credentials.ini")
    host = credentials.get("Mongo", "connection")
    user = credentials.get("Mongo", "user")
    password = credentials.get("Mongo", "password")
    db = credentials.get("Mongo", "database")
    connection_url = "mongodb://" + user + ":" + password + "@" + host + "/" + db + "?authSource=admin"
    client = MongoClient(connection_url)
    return client[db]

def update_database(user_id, db, access_token, expires_date, refresh_token, id):
    return db.users.update_one({'_id': user_id},
        {'$set': {
            'venmo': {
                'access_token': access_token,
                'expires_in': expires_date,
                'refresh_token': refresh_token,
                'id': id
                }
            },
        '$currentDate': {'lastModified': True}
        })

def get_access_token(user_id, response_url):
    config = ConfigParser.ConfigParser()
    config.read('credentials.ini')
    db = connect_to_mongo()
    venmo_auth = db.users.find_one({'_id': user_id}, {'venmo': 1})
    if (venmo_auth == None or 'venmo' not in venmo_auth or venmo_auth['venmo']['access_token'] == ''):
        user_doc = db.users.find_one({'_id': user_id})
        if (user_doc == None):
            create_user_doc = db.users.insert_one({'_id': user_id})
        create_venmo_auth = update_database(user_id, db, '', '', '', '')
        auth_url = 'https://api.venmo.com/v1/oauth/authorize?client_id=' + config.get('Venmo', 'clientId') + '&scope=make_payments%20access_payment_history%20access_feed%20access_profile%20access_email%20access_phone%20access_balance%20access_friends&response_type=code'
        url_message = ('Authenticate to Venmo with the following URL: ' + auth_url + ' then send back the auth code in this format\n'
                       'venmo code CODE')
        respond(url_message, response_url)
        return None
        
    else:
        expires_date = venmo_auth['venmo']['expires_in'].replace(tzinfo = pytz.utc)
        if (expires_date < datetime.datetime.utcnow().replace(tzinfo = pytz.utc)):
            post_data = {
                'client_id': config.get('Venmo', 'clientId'),
                'client_secret': config.get('Venmo', 'clientSecret'),
                'refresh_token': venmo_auth['venmo']['refresh_token']
                }
            response = requests.post('https://api.venmo.com/v1/oauth/access_token', post_data)
            response_dict = response.json()
            access_token = response_dict['access_token']
            expires_in = response_dict['expires_in']
            expires_date = (datetime.datetime.utcnow().replace(tzinfo = pytz.utc) + datetime.timedelta(seconds=expires_in))
            id = response_dict['user']['id']
            update_database(user_id, db, access_token, expires_date, response_dict['refresh_token'], id)
            return access_token
        return venmo_auth['venmo']['access_token']

def complete_auth(code, user_id, response_url):
    config = ConfigParser.ConfigParser()
    config.read('credentials.ini')
    db = connect_to_mongo()
    post_data = {
        'client_id': config.get('Venmo', 'clientId'),
        'client_secret': config.get('Venmo', 'clientSecret'),
        'code': code
        }
    response = requests.post('https://api.venmo.com/v1/oauth/access_token', post_data)
    response_dict = response.json()
    access_token = response_dict['access_token']
    expires_in = response_dict['expires_in']
    expires_date = (datetime.datetime.utcnow().replace(tzinfo = pytz.utc) + datetime.timedelta(seconds=expires_in))
    refresh_token = response_dict['refresh_token']
    id = response_dict['user']['id']
    update_access_token = update_database(user_id, db, access_token, expires_date, refresh_token, id)
    respond('Authentication complete!', response_url)

def _get_venmo_id(access_token):
    response = requests.get('http://api.venmo.com/v1/me?access_token=' + access_token)
    response_dict = response.json()
    if ('error' in response_dict):
        venmo_error(response_dict['error'], response_url)
        return ''
    return response_dict['data']['user']['id']

def _get_pagination(initial, access_token):
    final_list = []
    while True:
        final_list += initial['data']
        if (not initial['pagination'] or initial['pagination']['next'] == None):
            break
        else:
            response = requests.get(initial['pagination']['next'] + '&access_token=' + access_token)
            response_dict = response.json()
            if ('error' in response_dict):
                venmo_error(response_dict['error'], response_url)
                return []
            initial = response_dict
    return final_list

def _find_friend(list, username):
    for friend in list:
        if (friend['username'].lower() == username.lower()):
            return friend['id']
    return None

def get_venmo_balance(access_token, response_url):
    response = requests.get('https://api.venmo.com/v1/me?access_token=' + access_token)
    response_dict = response.json()
    if ('error' in response_dict):
        venmo_error(response_dict['error'], response_url)
        return
    respond(response_dict['data']['balance'], response_url)

def _get_friends(venmo_id, access_token, response_url):
    friends_response = requests.get('https://api.venmo.com/v1/users/' + venmo_id + '/friends?access_token=' + access_token)
    friends_response_dict = friends_response.json()
    if ('error' in friends_response_dict):
        venmo_error(friends_response_dict['error'], response_url)
        return []
    full = _get_pagination(friends_response_dict, access_token)
    return full

def venmo_payment(audience, which, amount, note, recipients, access_token, venmo_id, response_url):
    url = 'https://api.venmo.com/v1/payments'
    amount_str = str(amount)
    if (which == 'charge'):
        amount_str = '-' + amount_str
    full = _get_friends(venmo_id, access_token, response_url)
    final_message = ''
    for r in recipients:
        post_data = {
            'access_token': access_token
            }
        if r.startswith('phone:'):
            id = r[6:]
            post_data['phone'] = id
        elif r.startswith('email:'):
            id = r[6:]
            post_data['email'] = id
        else:
            id = _find_friend(full, r)
            if (id == None):
                parse_error('You are not friends with ' + r, response_url)
                return
            post_data['user_id'] = id
        post_data['note'] = note
        post_data['amount'] = amount_str
        post_data['audience'] = audience
        response = requests.post(url, post_data)
        response_dict = response.json()
        if ('error' in response_dict):
            final_message += response_dict['error']['message'] + '\n'
        else:
            name = ''
            target = response_dict['data']['payment']['target']
            if (target['type'] == 'user'):
                name = target['user']['display_name']
            elif (target['type'] == 'phone'):
                name = target['phone']
            elif (target['type'] == 'email'):
                name = target['email']
            if (amount_str.startswith('-')):
                final_message += 'Successfully charged ' + name + ' $' + '{:0,.2f}'.format(response_dict['data']['payment']['amount']) + ' for ' + response_dict['data']['payment']['note'] + '. Audience is ' + audience + '.\n'
            else:
                final_message += 'Successfully paid ' + name + ' $' + '{:0,.2f}'.format(response_dict['data']['payment']['amount']) + ' for ' + response_dict['data']['payment']['note'] + '. Audience is ' + audience + '.\n'
    respond(final_message, response_url)

def alias_user(user_id, id, alias, venmo_id, access_token, response_url):
    friends = _get_friends(venmo_id, access_token, response_url)
    friend_id = _find_friend(full, id)
    if (friend_id == None):
        parse_error('You are not friends with ' + id, response_url)
        return
    db = connect_to_mongo()
    db.users.update_one({'_id': user_id},
        {'$set': {
            'alias': {
                alias: friend_id
                }
            },
         '$currentDate': {'lastModified': True}
         })
    respond('Alias set!', response_url)
    return

def venmo_pending(which, access_token, venmo_id, response_url):
    message = ''
    url = 'https://api.venmo.com/v1/payments?access_token=' + access_token + '&status=pending'
    response = requests.get(url)
    response_dict = response.json()
    if ('error' in response_dict):
        venmo_error(response_dict['error'], response_url)
        return
    full = _get_pagination(response_dict, access_token)
    for pending in full:
        if (which == 'to'):
            if (pending['actor']['id'] != venmo_id):
                message += pending['actor']['display_name'] + ' requests $' + '{:0,.2f}'.format(pending['amount']) + ' for ' + pending['note'] + ' | ID: ' + pending['id'] + '\n'
        elif (which == 'from'):
            if (pending['actor']['id'] == venmo_id):
                if (pending['target']['type'] == 'user'):
                    message += pending['target']['user']['display_name'] + ' owes you $' + '{:0,.2f}'.format(pending['amount']) + ' ' + pending['note'] + ' | ID: ' + pending['id'] + '\n'
    if (message != ''):
        respond(message[0:-1], response_url)
    else:
        respond('No pending Venmos', response_url)

def venmo_complete(which, number, access_token, venmo_id, response_url):
    url = 'https://api.venmo.com/v1/payments/' + str(number)
    action = ''
    if (which == 'accept'):
        action = 'approve'
    elif (which == 'reject'):
        action = 'deny'
    elif (which == 'cancel'):
        action = 'cancel'
    check_url = 'https://api.venmo.com/v1/payments/' + str(number) + '?access_token=' + access_token
    check_response = requests.get(check_url)
    check_response_dict = check_response.json()
    if ('error' in check_response_dict):
        venmo_error(check_response_dict['error'], response_url)
        return
    if (check_response_dict['data']['actor']['id'] != venmo_id):
        if (action == 'cancel'):
            parse_error(check_response_dict['data']['actor']['display_name'] + ' requested $' + '{:0,.2f}'.format(check_response_dict['data']['amount']) + ' for ' + check_response_dict['data']['note'] + '. You cannot cancel it!', response_url)
            return
    else:
        if (action == 'approve' or action == 'deny'):
            parse_error('You requested $' + '{:0,.2f}'.format(check_response_dict['data']['amount']) + ' for ' + check_response_dict['data']['note'] + '. You can try venmo complete cancel ' + str(number) + " if you don't want to be paid back.", response_url)
            return
    put_data = {
        'access_token': access_token,
        'action': action
        }
    response = requests.put(url, put_data)
    response_dict = response.json()
    if ('error' in response_dict):
        venmo_error(response_dict['error'], response_url)
        return
    if (action == 'approve'):
        respond('Venmo completed!', response_url)
    elif (action == 'deny'):
        respond('Venmo denied!', response_url)
    elif (action == 'cancel'):
        respond('Venmo canceled!', response_url)

def help(response_url):
    message = ('Venmo help\n'
           'Commands:\n'
           'venmo balance\n'
           '    returns your Venmo balance\n'
           'venmo (audience) pay/charge amount for note to recipients\n'
           '    example: venmo public charge $10.00 for lunch to testuser phone:5555555555 email:example@example.com\n'
           '    audience (optional) = public OR friends OR private\n'
           '        defaults to friends if omitted\n'
           '    pay/charge = pay OR charge\n'
           '    amount = Venmo amount\n'
           '    note = Venmo message\n'
           '    recipients = list of recipients, can specify Venmo username, phone number prefixed with phone: or email prefixed with email:\n'
           'venmo alias id alias\n'
           '    example: venmo alias 4u$3r1d sam\n'
           '    set an alias for a Venmo username\n'
           '    id = Venmo username\n'
           '    alias = the alias for that user, must not contain spaces\n'
           'venmo pending (to OR from)\n'
           '    returns pending venmo charges, defaults to to\n'
           '    also returns ID for payment completion\n'
           'venmo complete accept/reject/cancel number\n'
           '    accept OR reject pending incoming Venmos with the given ID\n'
           '    cancel pending outgoing Venmos with the given ID\n'
           'venmo code code\n'
           '    code = Venmo authentication code\n'
           'venmo help\n'
           '    this help message')
    respond(message, response_url)

def venmo_error(dict, response_url):
    respond(dict['message'], response_url)

def parse_error(error_message, response_url):
    respond(error_message, response_url)

def _find_last_str_in_list(list, str):
    index = -1
    for i in range(len(list)):
        if (list[i].lower() == str.lower()):
            index = i
    return index

def parse_message(message, access_token, user_id, venmo_id, response_url):
    split_message = message.split()
    if (len(split_message) == 1):
        help(response_url)
    elif (split_message[1].lower() == 'help'):
        help(response_url)
    elif (split_message[1].lower() == 'code'):
        complete_auth(split_message[2], user_id, response_url)
    elif (split_message[1].lower() == 'balance'):
        get_venmo_balance(access_token, response_url)
    elif (split_message[1].lower() == 'pending'):
        if (len(split_message) == 2):
            venmo_pending('to', access_token, venmo_id, response_url)
        elif (len(split_message) == 3):
            which = split_message[2].lower()
            if (which == 'to' or which == 'from'):
                venmo_pending(which, access_token, venmo_id, response_url)
            else:
                parse_error('Valid pending commands\npending\npending to\npending from', response_url)
        else:
            parse_error('Valid pending commands\npending\npending to\npending from', response_url)
    elif (split_message[1].lower() == 'complete'):
        if (len(split_message) == 4):
            which = split_message[2].lower()
            if (which == 'accept' or which == 'reject' or which == 'cancel'):
                number = -1
                try:
                    number = int(split_message[3])
                except:
                    parse_error('Payment completion number must be a number', response_url)
                    return
                venmo_complete(which, number, access_token, venmo_id, response_url)
            else:
                parse_error('Valid complete commands\nvenmo complete accept #\nvenmo complete reject #\nvenmo complete cancel #', response_url)
        else:
            parse_error('Valid complete commands\nvenmo complete accept #\nvenmo complete reject #\nvenmo complete cancel #', response_url)
    elif (split_message[1].lower() == 'alias'):
        if (len(split_message) == 4):
            id = split_message[2]
            alias = split_message[3]
            alias_user(user_id, id, alias, venmo_id, access_token, response_url)
        else:
            parse_error('Invalid alias command, your alias probably has a space in it', response_url)
    elif (len(split_message) <= 2):
        parse_error('Invalid payment string', response_url)
    elif (split_message[1].lower() == 'charge' or split_message[2].lower() == 'charge' or
          split_message[1].lower() == 'pay' or split_message[2].lower() == 'pay'):
        audience = 'friends'
        if (split_message[2].lower() == 'charge' or split_message[2].lower() == 'pay'):
            audience = split_message[1].lower()
            if (audience != 'public' and audience != 'friends' and audience != 'private'):
                parse_error('Valid payment sharing commands\npublic\nfriend\nprivate', response_url)
                return
            del split_message[1]
        which = split_message[1]
        if (len(split_message) <= 6):
            parse_error('Invalid payment string', response_url)
            return
        amount_str = split_message[2]
        amount = 0
        if (amount_str.startswith('$')):
            amount_str = amount_str[1:]
        try:
            amount = float(amount_str)
        except:
            parse_error('Invalid amount', response_url)
            return
        if (split_message[3].lower() != 'for'):
            parse_error('Invalid payment string', response_url)
            return
        to_index = _find_last_str_in_list(split_message, 'to')
        if (to_index < 5):
            parse_error('Could not find recipients', response_url)
            return
        note = ' '.join(split_message[4:to_index])
        recipients = split_message[to_index + 1:]
        venmo_payment(audience, which, amount, note, recipients, access_token, venmo_id, response_url)

if __name__ == '__main__':
    app.run(debug=False, use_reloader=False)