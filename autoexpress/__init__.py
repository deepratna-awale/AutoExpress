from flask import Flask
import sys
import os

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, parent_dir)

autoexpress = Flask(__name__)

from autoexpress.views import autoexpress

if __name__ == "__main__":
    autoexpress.run(debug=True)
