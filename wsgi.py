import config
import ConfigParser
import json
from venmo import app

if __name__ == "__main__":
    config.credentials = ConfigParser.ConfigParser()
    config.credentials.read('credentials.ini')
    with open('settings.json', 'r') as f:
        config.workspaces = json.loads(f.read())
    app.run(debug=False, port=5678)
