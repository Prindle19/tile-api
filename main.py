import json
import urllib
import webapp2
import logging
from google.appengine.api import urlfetch
from google.appengine.api import memcache
from google.appengine.ext import db

# Set the projecet's API Key (Credential from Developer Console)
apiKey = 'AIzaSyBKElXf-MOGx7C5N08VNHIwgAEC7s77Xzg'

# Define the Cloud Datastore Model for storing tokens
class Token(db.Model):
  token = db.StringProperty()

# Generate a new session token and store it in Memcache and Datastore
# Requires both the JSON that gets POSTed to  Tile API createSession
# And the name of the style that will be saved
def newToken(payload,keyName):
  try:
    # Using urlfetch on AppEngine, you must explicitly state the referer in the header
    # The referer must match one of the approved referer URLs from Developer Console
    headers = {'Content-Type': 'application/json', 'Referer': 'https://tile-sessions.appspot.com/'}
    result = urlfetch.fetch(
        url="https://www.googleapis.com/tile/v1/createSession?key={0}".format(apiKey),
        payload=payload,
        method=urlfetch.POST,
        headers=headers)
    # Extract the newly created session token from the Tile API response
    session = json.loads(result.content)
    token = session["session"]
    # Store the session token in Memcache
    memcache.add(keyName, token)
    # Also store the session token in Datastore incase there is a Memcache miss
    dbToken = Token(key_name=keyName,token=token)
    dbToken.put()
  except urlfetch.Error, e:
    logging.error("Caught exception fetching url {}".format(e))

# Called by the cron job, defines the tile styles for the application
class sessionCron(webapp2.RequestHandler):
  def get(self):
    # Simple Satellite Tile Style with no overlays
    satValues = {
          "mapType": "satellite",
          "language": "en-US",
          "region": "us",
          "overlay":  "false",
          "scale": "scaleFactor1x"
    }
    # Complex Styled Maps Tile Style with no overlays
    styleValues = {
          "mapType": "roadmap",
          "language": "en-US",
          "region": "us",
          "layerTypes": ["layerRoadmap"],
          "overlay":  "false",
          "scale": "scaleFactor1x",
          "styles": [{"featureType":"water","elementType":"geometry",
          	"stylers":[{"color":"#ffdfa6"}]},{"featureType":"landscape",
          	"elementType":"geometry","stylers":[{"color":"#b52127"}]},
          	{"featureType":"poi","elementType":"geometry",
          	"stylers":[{"color":"#c5531b"}]},{"featureType":"road.highway",
          	"elementType":"geometry.fill","stylers":[{"color":"#74001b"},
          	{"lightness":-10}]},{"featureType":"road.highway","elementType":"geometry.stroke",
          	"stylers":[{"color":"#da3c3c"}]},{"featureType":"road.arterial",
          	"elementType":"geometry.fill","stylers":[{"color":"#74001b"}]},
          	{"featureType":"road.arterial","elementType":"geometry.stroke",
          	"stylers":[{"color":"#da3c3c"}]},{"featureType":"road.local","elementType":"geometry.fill",
          	"stylers":[{"color":"#990c19"}]},{"elementType":"labels.text.fill","stylers":[{"color":"#ffffff"}]},
          	{"elementType":"labels.text.stroke","stylers":[{"color":"#74001b"},{"lightness":-8}]},
          	{"featureType":"transit","elementType":"geometry","stylers":[{"color":"#6a0d10"},{"visibility":"on"}]},
          	{"featureType":"administrative","elementType":"geometry","stylers":[{"color":"#ffdfa6"},{"weight":1}]},
          	{"featureType":"road.local","elementType":"geometry.stroke","stylers":[{"visibility":"off"}]}]
    }
    # Simple Terrain Tile Style with no overlays
    terrainValues = {
          "mapType": "terrain",
          "language": "en-US",
          "region": "us",
          "layerTypes": ["layerRoadmap"],
          "overlay":  "false",
          "scale": "scaleFactor1x"
    }
    # Create the new session tokens
    newToken(json.dumps(satValues),"satToken")
    newToken(json.dumps(styleValues),"styleToken")
    newToken(json.dumps(terrainValues),"terrainToken")
    logging.info("Refreshed all Session Tokens")

# Provides the basic Tile Proxy for the application
class getTile(webapp2.RequestHandler):
  # Requires: the Z / X / Y parameters of the tile requested
  # "layer" must be one of "satellite", "styled", or "terrain", matching the defined Tile Styles
  # "redirect" must be true or false, and determines whether the app will redirect the tile request
  # directly to Tile API or if the app will actually proxy the request and traffic through AppEngine
   def get(self):
    z = self.request.get("z")
    x = self.request.get("x")
    y = self.request.get("y")
    redirect = self.request.get("redirect")
    layer = self.request.get("layer")
    # Determine which layer was requested
    if layer == "satellite":
      # Try to get the session token from Memcache
      data = memcache.get("satToken")
      if data is not None:
        session = data
      else:
        # If the session token was not in Memcache, or if there was a Memcache miss, fail over to Datastore
        token = Token.get_by_key_name("satToken")
        session = token.token
    elif layer == "styled":
      data = memcache.get("styleToken")
      if data is not None:
        session = data
      else:
        token = Token.get_by_key_name("styleToken")
        session = token.token
    elif layer == "terrain":
      data = memcache.get("terrainToken")
      if data is not None:
        session = data
      else:
        token = Token.get_by_key_name("terrainToken")
        session = token.token
    # Create a python dictionary with the Tile API key and session token values
    params = {
      "key": apiKey,
      "session": session
    }
    # URL Encode the dictionary for use with urlfetch or client redirect
    url_params = urllib.urlencode(params)
    # Create the valid, Tile API Tile URL with all required parameters
    url = "https://www.googleapis.com/tile/v1/tiles/{0}/{1}/{2}/?{3}".format(z,x,y,url_params)
    # If redirect is true, redirect the client directly to Tile API
    if redirect == "true":
      self.redirect(url)
  # Else, construct a urlfetch for the URL, retrieve the binary data from Tile API and write out an image to the requester
    else:
      try:
        headers = {'Referer': 'https://tile-sessions.appspot.com/'}
        result = urlfetch.fetch(url=url,headers=headers)
        if result.status_code == 200:
          self.response.headers['Content-Type'] = 'image/jpg'
          self.response.write(result.content)
        else:
          self.response.status = result.status_code
      except urlfetch.Error, e:
        logging.error("Caught exception fetching url {}".format(e))

app = webapp2.WSGIApplication([
    ('/getTile/', getTile),('/sessionCron/', sessionCron)
    ], debug=True)
    
