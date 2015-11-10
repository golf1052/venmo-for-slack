# YHackSlackPack Venmo Slash Command
Now you have no excuse not to pay your boss back for lunch.

Supports
- View balance
- Pay/Charge by username, phone, or email
- View pending Venmos
- Complete/reject a pending Venmo

# Usage
- venmo balance
  - returns your Venmo balance
- venmo (audience) pay/charge amount for note to recipients
  - example: venmo public charge $10.00 for lunch to testuser phone:5555555555 email:example@example.com
  - audience (optional) = public OR friends OR private
    - defaults to friends if omitted
  - pay/charge = pay OR charge
  - amount = Venmo amount
  - note = Venmo message
  - recipients = list of recipients, can specify Venmo username, phone number prefixed with phone: or email prefixed with email:
- venmo pending (to OR from)
  - returns pending venmo charges, defaults to to
  - also returns ID for payment completion
- venmo complete accept/reject number
  - accept OR reject a payment with the given ID
- venmo code code
  - code = Venmo authentication code
- venmo help
  - this help message
  
# Setup
## Mongo
Setup a Mongo database somwhere that your server can access. The app uses a Mongo database to store auth information for users.

## Venmo
Register a Venmo app [here](https://venmo.com/account/settings/developer). The client id and client secret will go in your credentials.ini file.

## Credentials
First setup a credentials.ini file in the venmo folder. There is an example credentials_sample.ini file that should show you want you need.

## Flask
The bot integration was turned into a Flask app so that it could become a slash command on Venmo. The app needs to be setup on a server so that Slack can send POST requests to it.

## Slack
Once the app is up and running create a new slash command integration on Slack. Set the command as /venmo and set the URL to where ever you set up your Flask app on. Save the integration and you should be good to go!