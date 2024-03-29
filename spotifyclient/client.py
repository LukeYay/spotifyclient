import base64
import json
from datetime import datetime, timedelta

import requests


BASE_URL = 'https://api.spotify.com/v1'

AUTH_PATH, AUTH_METHOD = '/api/token', 'POST'
PLAYER_PATH = '/me/player'
TRACKS_PATH = '/tracks'

METHODS = {
    'get': requests.get,
    'post': requests.post,
    'put': requests.put,
}


class Spotify:

    def __init__(self, client_id, client_secret, refresh_token):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None
        self.token_expires = None

    # region AUTH

    def _get_base64_auth(self):
        client_combined = self.client_id + ':' + self.client_secret
        return base64.b64encode(client_combined.encode("utf-8"))

    def _get_generic_access_token(self):
        access_token, _ = self._get_access_token(self._get_generic_auth_params())
        return access_token

    def _get_user_access_token(self):
        access_token, _ = self._get_access_token(self._get_user_auth_params())
        return access_token

    @staticmethod
    def _get_generic_auth_params():
        return {'grant_type': 'client_credentials'}

    def _get_user_auth_params(self):
        if self.refresh_token is None:
            raise PermissionError()
        return {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token
        }

    def _get_access_token(self, auth_params):
        if self.access_token is not None and self.token_expires > datetime.utcnow():
            return self.access_token, self.token_expires

        header_auth = {
            'Authorization': 'Basic '.encode() + self._get_base64_auth(),
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        r = requests.post('https://accounts.spotify.com' + AUTH_PATH,
                          headers=header_auth,
                          params=auth_params)

        if 200 <= r.status_code < 400:
            response_auth = r.json()
            if 'access_token' in response_auth:
                self.access_token = response_auth['access_token']
                self.token_expires = datetime.utcnow() + timedelta(seconds=response_auth['expires_in'])
                return self.access_token, self.token_expires

        return None, None

    def refresh_user_access_token(self):
        if self.refresh_token is None:
            raise PermissionError()

        header_auth = {
            'Authorization': 'Basic '.encode() + self._get_base64_auth(),
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        auth_params = {
            'refresh_token': self.refresh_token,
            'grant_type': 'refresh_token'
        }

        r = requests.post('https://accounts.spotify.com' + AUTH_PATH,
                          headers=header_auth,
                          params=auth_params)

        if 200 <= r.status_code < 400:
            response_auth = r.json()
            if 'access_token' in response_auth:
                self.access_token = response_auth['access_token']
                self.token_expires = datetime.utcnow() + timedelta(seconds=response_auth['expires_in'])
                return self.access_token, self.token_expires

        return

    def _get_api_headers(self):
        return {'Authorization': f'Bearer {self._get_generic_access_token()}'}

    def get_user_api_headers(self):
        return {'Authorization': f'Bearer {self._get_user_access_token()}'}

    # endregion

    # region VOLUME

    def get_current_volume(self, device_id):
        result, devices_data = self._get('devices')
        if not result:
            return None

        devices = devices_data['devices']
        for device in devices:
            if device['id'] == device_id:
                return device['volume_percent']

        return None

    def change_volume(self, device_id, change):
        current_volume = self.get_current_volume(device_id)
        if current_volume is None:
            return False, 'Failed to change volume: Error getting current volume'
        return self.set_device_volume(min(max(current_volume + change, 0), 100))

    def set_device_volume(self, volume):
        return self._put('volume', query_params={'volume_percent': volume})

    def increase_volume(self, device_id):
        return self.change_volume(device_id, change=+10)

    def decrease_volume(self, device_id):
        return self.change_volume(device_id, change=-10)

    # endregion

    # region PLAYING

    def parse_play_command(self, device_id, command):
        parts = command.split(' ')
        if len(parts) == 1:
            return self.start_playing(device_id)

        if parts[0].lower() != 'play':
            return False, f'Invalid command: {command}'

        search_type = 'artist,album,track'
        if len(parts) == 2:
            search_term = parts[1]
        else:
            if parts[1] in ['artist', 'album', 'track']:
                search_type = [parts[1]]
                search_term = ' '.join(parts[2:])
            else:
                search_term = ' '.join(parts[1:])

        results = self.do_search(search_term, search_type=search_type, exact_match=True)
        if results is None:
            return False, 'Failed to get any search results'

        for result_id, result in iter(results['artists'].items()):
            if result['name'].lower() == search_term.lower():
                return self.play_artist_by_uri(device_id, result['uri'])

        for result_id, result in iter(results['albums'].items()):
            if result['name'].lower() == search_term.lower():
                return self.play_album_by_uri(device_id, result['uri'])

        for result_id, result in iter(results['tracks'].items()):
            if result['name'].lower() == search_term.lower():
                return self.play_song_by_uri(device_id, result['uri'])

        return False, f'No result found for {search_type} \'{search_term}\''

    def resume_song(self, device_id):
        return self.start_playing(device_id)

    def start_playing(self, device_id):
        return self._put('play', query_params={'device_id': device_id})

    def pause_song(self, device_id):
        return self._put('pause', query_params={'device_id': device_id})

    def play_next_track(self, device_id):
        return self._post('next', query_params={'device_id': device_id})

    def play_previous_track(self, device_id):
        return self._post('previous', query_params={'device_id': device_id})

    def restart_track(self, device_id):
        return self._put('seek', query_params={'device_id': device_id}, data_params={'position_ms': 0})

    def play_song_by_uri(self, device_id, uri):
        return self._put('play', query_params={'device_id': device_id}, data_params={'uris': [uri]})

    def play_artist_by_uri(self, device_id, uri):
        return self._put('play', query_params={'device_id': device_id}, data_params={'context_uri': uri})

    def play_album_by_uri(self, device_id, uri):
        return self._put('play', query_params={'device_id': device_id}, data_params={'context_uri': uri})

    def get_user_currently_playing(self):
        raise NotImplementedError()

    def get_current_device(self, has_retried=False):
        profile_player_url = BASE_URL + PLAYER_PATH + '/devices'

        r = requests.get(profile_player_url, headers=self.get_user_api_headers())

        if r.status_code == 401:
            if not has_retried:
                return self.get_current_device(True)
            else:
                return f'Failed to get current device| Code: {r.status_code}', None

        for device in r.json()['devices']:
            if device['is_active']:
                return None, device['id']

        return 'No active devices', None

    def get_available_devices(self, has_retried=False):
        profile_player_url = BASE_URL + PLAYER_PATH + '/devices'

        r = requests.get(profile_player_url, headers=self.get_user_api_headers())

        if r.status_code == 401:
            if not has_retried:
                return self.get_available_devices(True)
            else:
                return f'Failed to refresh access: Type: "get" | Command: "devices" | Code: {r.status_code} ' \
                       f'| Text: {r.text}', None

        returned_devices = {}
        for index, device in enumerate(r.json()['devices']):
            returned_devices[index+1] = {
                'name': device['name'],
                'id': device['id']
            }
        return None, returned_devices

    def get_recently_played(self, as_json=False, all_data=False):
        profile_player_url = BASE_URL + PLAYER_PATH + '/recently-played'

        r = requests.get(profile_player_url, headers=self.get_user_api_headers())

        has_retried = False
        if r.status_code == 401:
            if not has_retried:
                return self.get_available_devices(True)
            else:
                return f'Unauthorised | Code: {r.status_code}', None

        recent_data = r.json()

        if all_data:
            for recent_item in recent_data['items']:
                recent_item['played_at_datetime'] = datetime.strptime(recent_item['played_at'], "%Y-%m-%dT%H:%M:%S.%fZ")
                recent_item['played_at_friendly'] = recent_item['played_at_datetime'].strftime('%-d %b %Y %H:%M')
            return None, recent_data['items']

        recent_items = []
        for recent_item in recent_data['items']:
            artist_name = recent_item['track']['artists'][0]['name']
            track_name = recent_item['track']['name']
            album_name = recent_item['track']['album']['name']
            preview_url = recent_item['track']['preview_url']
            played_at = recent_item['played_at']

            played_at_datetime = datetime.strptime(played_at, "%Y-%m-%dT%H:%M:%S.%fZ")
            played_at_friendly = played_at_datetime.strftime('%-d %b %Y %H:%M')

            album_image_url = recent_item['track']['album']['images'][0]['url']

            if as_json:
                recent_items.append({
                    'artist_name': artist_name,
                    'track_name': track_name,
                    'album_name': album_name,
                    'played_at_friendly': played_at_friendly,
                    'preview_url': preview_url,
                    'album_image_url': album_image_url
                })
            else:
                recent_items.append((
                    artist_name, track_name, album_name, played_at_friendly, preview_url, album_image_url)
                )

        return None, recent_items

    # endregion

    # region API

    def _get(self, command, query_params=None, data_params=None):
        return self.submit_command('get', command, query_params, data_params)

    def _post(self, command, query_params=None, data_params=None):
        return self.submit_command('post', command, query_params, data_params)

    def _put(self, command, query_params=None, data_params=None):
        return self.submit_command('put', command, query_params, data_params)

    def submit_command(self, method, command, additional_query_params, additional_body_params, has_retried=False):
        if method not in METHODS.keys():
            return False, f'Unknown command type "{method}"'

        request_url = BASE_URL + PLAYER_PATH + '/' + command

        r = METHODS[method](
            request_url,
            headers=self.get_user_api_headers(),
            params=additional_query_params,
            json=additional_body_params
        )

        if r.status_code == 401 and not has_retried:
            return self.submit_command(method, command, additional_query_params, additional_body_params, True)

        return r.ok, 'Success' if r.status_code == 204 else r.json()

    # endregion

    # region DATA

    def get_track_by_id(self, track_id):
        tracks_full_url = BASE_URL + TRACKS_PATH + '/' + track_id

        r = requests.get(tracks_full_url, headers=self._get_api_headers())

        return None, r.json()

    # endregion

    # region SEARCH

    def search_tracks(self, search_term, types, limit=50, exact_match=False, all_pages=False):

        def extract_artist(artist, results):
            index = len(results)
            name = artist['name']
            uri = artist['uri']
            results[index] = {}
            results[index]['name'] = name
            results[index]['uri'] = uri

        def extract_album(album, results):
            index = len(results)
            name = album['name']
            uri = album['uri']
            artists = album['artists']
            artist_names = []
            for artist in artists:
                artist_names.append(artist['name'])
            results[index] = {}
            results[index]['display_name'] = name + '(' + ', '.join(artist_names) + ')'
            results[index]['name'] = name
            results[index]['uri'] = uri

        def extract_track(track, results):
            index = len(results)
            name = track['name']
            uri = track['uri']
            artists = track['artists']
            artist_names = []
            for artist in artists:
                artist_names.append(artist['name'])
            album = track['album']
            album_name = album['name']

            results[index] = {}
            results[index]['display_name'] = name + ' (' + album_name + ' by ' + ', '.join(artist_names) + ')'
            results[index]['name'] = name
            results[index]['uri'] = uri

        request_url = BASE_URL + '/search'
        params = {
            'q': ' '.join([f'{t}:{search_term}' for t in types]) if exact_match else search_term,
            'type': types,
            'limit': limit
        }
        r = requests.get(request_url, headers=self._get_api_headers(), params=params)
        if r.status_code != 200:
            error = r.json()['error']
            print('Error getting results: ' + error['message'])
            return None

        results_data = r.json()

        artists_data = results_data.get('artists', [])
        albums_data = results_data.get('albums', [])
        tracks_data = results_data.get('tracks', [])

        search_results = {
            'artists': {},
            'albums': {},
            'tracks': {}
        }

        if artists_data:
            search_results['artists'] = self.extract_data('artists', artists_data, all_pages, extract_artist)

        if albums_data:
            search_results['albums'] = self.extract_data('albums', albums_data, all_pages, extract_album)

        if tracks_data:
            search_results['tracks'] = self.extract_data('tracks', tracks_data, all_pages, extract_track)

        return search_results

    def extract_data(self, field, data, all_pages, extract_method):
        results = {}

        for item in data['items']:
            extract_method(item, results)

        next_items = data['next']

        if all_pages:

            while next_items and len(next_items) > 0:
                # time.sleep(1)
                r = requests.get(next_items, headers=self._get_api_headers())
                if r.status_code != 200:
                    error = r.json()['error']
                    print('Error getting results: ' + error['message'])
                    break

                data = r.json()[field]

                for item in data['items']:
                    extract_method(item, results)

                next_items = data['next']

        return results

    def do_search(self, search_term, search_type='artist,track,album', exact_match=False):
        return self.search_tracks(search_term, search_type, exact_match=exact_match)

    # endregion
