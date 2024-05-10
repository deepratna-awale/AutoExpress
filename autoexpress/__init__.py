from flask import Flask
import sys
sys.path.insert(0, "D:/Workspace/AutoExpress")

autoexpress = Flask(__name__)

from autoexpress.views import autoexpress

if __name__ == "__main__":
    autoexpress.run(debug=True)
