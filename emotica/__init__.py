from flask import Flask
import sys
import os

parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, parent_dir)

emotica = Flask(__name__)

from emotica.views import emotica

if __name__ == "__main__":
    emotica.run()
