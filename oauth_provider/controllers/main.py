import functools
import logging
import simplejson

import openerp
from openerp import SUPERUSER_ID
from openerp import http
from openerp.http import request
from openerp.addons.web.controllers.main import db_monodb, ensure_db, set_cookie_and_redirect, login_and_redirect
from openerp.addons.auth_signup.controllers.main import AuthSignupHome as Home
from openerp.modules.registry import RegistryManager
from openerp.tools.translate import _
import werkzeug

_logger = logging.getLogger(__name__)

from ..validators import server

from oauthlib.oauth2.rfc6749 import errors
from oauthlib.common import urlencode, urlencoded, quote
from urlparse import urlparse, parse_qs, urlunparse

# see https://oauthlib.readthedocs.org/en/latest/oauth2/server.html
class OAuth2(http.Controller):
    def __init__(self):
        self._server = server

    def _get_escaped_full_path(self, request):
        """
        Django considers "safe" some characters that aren't so for oauthlib. We have to search for
        them and properly escape.
        TODO: is it correct for openerp?
        """
        parsed = list(urlparse(request.httprequest.path))
        unsafe = set(c for c in parsed[4]).difference(urlencoded)
        for c in unsafe:
            parsed[4] = parsed[4].replace(c, quote(c, safe=''))

        return urlunparse(parsed)

    def _extract_params(self, request, post_dict):
        """
        Extract parameters from the Django request object. Such parameters will then be passed to
        OAuthLib to build its own Request object
        """
        uri = self._get_escaped_full_path(request)
        http_method = request.httprequest.method

        headers = dict(request.httprequest.headers.items())
        if 'wsgi.input' in headers:
            del headers['wsgi.input']
        if 'wsgi.errors' in headers:
            del headers['wsgi.errors']
        if 'HTTP_AUTHORIZATION' in headers:
            headers['Authorization'] = headers['HTTP_AUTHORIZATION']
        body = urlencode(post_dict.items())
        return uri, http_method, body, headers

    def _response_from_error(self, e):
        _logger.info("Error %s", e)
        return 'Error (TODO)'
    def _response(self, headers, body, status=200):
        response = werkzeug.Response(response=body, status=status, headers=headers)
        return response

    @http.route('/oauth2/auth', type='http', auth='public')
    def auth(self, **kw):
        # kw:
        #
        # state: {"p": 1, "r": "%2Fweb%2Flogin%3F", "d": "some-test-3"}
        # redirect_uri: https://example.odoo.com/auth_oauth/signin
        # response_type: token
        # client_id: d885dde2-0168-4650-9a32-ceb058e652a2
        # debug: False
        # scope: userinfo
        uri, http_method, body, headers = self._extract_params(request, kw)

        client_redirect = kw.get('redirect')

        user = request.registry['res.users'].browse(request.cr, SUPERUSER_ID, request.uid)

        try:
            scopes, credentials = self._server.validate_authorization_request(
                uri, http_method, body, headers)

        # Errors that should be shown to the user on the provider website
        except errors.FatalClientError as e:
            return self._response_from_error(e)

        # Errors embedded in the redirect URI back to the client
        except errors.OAuth2Error as e:
            return self._response({'Location':e.redirect_uri}, None, 302)


        if  user.login == 'public':

            params = {'mode':'login',
                      'scope':kw.get('scope'),
                      #'debug':1,
                      #'login':?,
                      #'redirect_hostname':TODO,
                      'redirect': '/oauth2/auth?%s' % werkzeug.url_encode(kw)
            }
            return self._response({'Location':'/web/login?%s' % werkzeug.url_encode(params)}, None, 302)
        else:
            credentials.update({'user':user})
        
            try:
                headers, body, status = self._server.create_authorization_response(
                uri, http_method, body, headers, scopes, credentials)
                return self._response(headers, body, status)
        
            except errors.FatalClientError as e:
                return self._response_from_error(e)

    #@http.route('/web/login', type='http', auth='none')

    @http.route('/oauth2/tokeninfo', type='http', auth='none')
    def tokeninfo(self, **kw):
        uri, http_method, body, headers = self._extract_params(request, kw)

        is_valid, req = self._server.verify_request(uri, http_method, body, headers)
        partner = req.user.partner_id

        headers = None
        body = simplejson.dumps({'user_id':partner.id,
                                 'email':partner.email,
                                 'name':partner.name})
        status = 200

        return self._response(headers, body, status)
