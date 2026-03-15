# Original (Spotipy): Copyright (c) 2021 Paul Lamere (MIT License)
# spotNoAPI: Copyright (c) 2026 Merlin Sievers (AGPLv3)

""" A simple and thin Python library for the Spotify Web API """

__all__ = ["Spotify", "SpotifyException"]

import json
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any
import warnings

import requests
from requests.adapters import HTTPAdapter

from spotipy.exceptions import SpotifyException, SpotifyNoAPIExceptionUnsupported, SpotifyNoAPIExceptionUnsupportedPRsWelcome, SpotifyNoAPIExceptionUnsupportedProbablyImpossible
from spotipy.noapi import Album, Artist, Search, Track, Playlist, Image
from spotipy.noapi import NoAPI
from spotipy.util import REQUESTS_SESSION, Retry
from spotipy.oauth2 import SpotifyAuthBase, SpotifyClientCredentials, SpotifyOAuth

logger = logging.getLogger(__name__)


class Spotify:
    """
        Example usage::

            import spotipy

            urn = 'spotify:artist:3jOstUTkEu2JkjvRdBA5Gu'
            sp = spotipy.Spotify()

            artist = sp.artist(urn)
            print(artist)

            user = sp.user('plamere')
            print(user)
    """
    max_retries: int = 3
    default_retry_codes: Sequence[int] = (429, 500, 502, 503, 504)
    country_codes: list[str] = [
        "AD",
        "AR",
        "AU",
        "AT",
        "BE",
        "BO",
        "BR",
        "BG",
        "CA",
        "CL",
        "CO",
        "CR",
        "CY",
        "CZ",
        "DK",
        "DO",
        "EC",
        "SV",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "GT",
        "HN",
        "HK",
        "HU",
        "IS",
        "ID",
        "IE",
        "IT",
        "JP",
        "LV",
        "LI",
        "LT",
        "LU",
        "MY",
        "MT",
        "MX",
        "MC",
        "NL",
        "NZ",
        "NI",
        "NO",
        "PA",
        "PY",
        "PE",
        "PH",
        "PL",
        "PT",
        "SG",
        "ES",
        "SK",
        "SE",
        "CH",
        "TW",
        "TR",
        "GB",
        "US",
        "UY"]

    # Spotify URI scheme defined in [1], and the ID format as base-62 in [2].
    #
    # Unfortunately the IANA specification is out of date and doesn't include the new types
    # show and episode. Additionally, for the user URI, it does not specify which characters
    # are valid for usernames, so the assumption is alphanumeric which coincidentally are also
    # the same ones base-62 uses.
    # In limited manual exploration this seems to hold true, as newly accounts are assigned an
    # identifier that looks like the base-62 of all other IDs, but some older accounts only have
    # numbers and even older ones seemed to have been allowed to freely pick this name.
    #
    # [1] https://www.iana.org/assignments/uri-schemes/prov/spotify
    # [2] https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids
    _regex_spotify_uri: str = r'^spotify:(?:(?P<type>track|artist|album|playlist|show|episode|audiobook):(?P<id>[0-9A-Za-z]+)|user:(?P<username>[0-9A-Za-z]+):playlist:(?P<playlistid>[0-9A-Za-z]+))$'  # noqa: E501

    # Spotify URLs are defined at [1]. The assumption is made that they are all
    # pointing to open.spotify.com, so a regex is used to parse them as well,
    # instead of a more complex URL parsing function.
    # Spotify recently added "/intl-<countrycode>" to their links. This change is undocumented.
    # There is an assumption that the country code uses the ISO 3166-1 alpha-2 standard [2],
    # but this has not been confirmed yet. Spotipy has no use for this, so it gets ignored.
    #
    # [1] https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids
    # [2] https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2
    _regex_spotify_url: str = r'^(http[s]?:\/\/)?open.spotify.com\/(intl-\w\w\/)?(?P<type>track|artist|album|playlist|show|episode|user|audiobook)\/(?P<id>[0-9A-Za-z]+)(\?.*)?$'  # noqa: E501

    _regex_base62: str = r'^[0-9A-Za-z]+$'

    def __init__(
        self,
        auth: str | None = None,
        requests_session: bool | requests.Session = True,
        client_credentials_manager: SpotifyClientCredentials | None = None,
        oauth_manager: SpotifyOAuth | None = None,
        auth_manager: SpotifyAuthBase | None = None,
        proxies=None,
        requests_timeout: int = 5,
        status_forcelist=None,
        retries: int = max_retries,
        status_retries: int = max_retries,
        backoff_factor: float = 0.3,
        language: str | None = None,
    ):
        """
        Creates a Spotify API client.

        :param auth: An access token (optional)
        :param requests_session:
            A Requests session object or a truthy value to create one.
            A falsy value disables sessions.
            It should generally be a good idea to keep sessions enabled
            for performance reasons (connection pooling).
        :param client_credentials_manager:
            SpotifyClientCredentials object
        :param oauth_manager:
            SpotifyOAuth object
        :param auth_manager:
            SpotifyOauth, SpotifyClientCredentials,
            or SpotifyImplicitGrant object
        :param proxies:
            Definition of proxies (optional).
            See Requests doc https://2.python-requests.org/en/master/user/advanced/#proxies
        :param requests_timeout:
            Tell Requests to stop waiting for a response after a given
            number of seconds
        :param status_forcelist:
            Tell requests what type of status codes retries should occur on
        :param retries:
            Total number of retries to allow
        :param status_retries:
            Number of times to retry on bad status codes
        :param backoff_factor:
            A backoff factor to apply between attempts after the second try
            See urllib3 https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html
        :param language:
            The language parameter advertises what language the user prefers to see.
            See ISO-639-1 language code: https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes
        """
        self.prefix: str | None = "https://api.spotify.com/v1/"
        self._auth: str | None = auth
        if auth is not None:
            logger.warning(f"You specified an auth token, but it is not used in SpotNoAPI.")
        self.client_credentials_manager: SpotifyClientCredentials | None = client_credentials_manager
        if client_credentials_manager is not None:
            logger.warning(f"You specified a client credentials manager, but it is not used in SpotNoAPI.")
        self.oauth_manager: SpotifyOAuth | None = oauth_manager
        if oauth_manager is not None:
            logger.warning(f"You specified an oauth manager, but it is not used in SpotNoAPI.")
        self._auth_manager: SpotifyAuthBase | None = None
        self.auth_manager = auth_manager
        if proxies != None:
            # proxies not implemented yet, but given that we only use requests, that should be straight forward to implement
            raise SpotifyNoAPIExceptionUnsupportedPRsWelcome
        self.proxies = proxies
        self.requests_timeout = requests_timeout
        self.status_forcelist = status_forcelist or self.default_retry_codes
        self.backoff_factor = backoff_factor
        self.retries = retries
        self.status_retries = status_retries
        self.language = language
        if language is not None:
            logger.warning(f"You set specified language {language}, but language is currently not used in SpotNoAPI.")

        if isinstance(requests_session, requests.Session):
            self._session: requests.Session | Any = requests_session  # pyright:ignore[reportExplicitAny]
        else:
            if requests_session:  # Build a new session.
                self._build_session()
            else:  # Use the Requests API module as a "session".
                self._session = requests.api

    def set_auth(self, auth: str):
        self._auth = auth

    @property
    def auth_manager(self) -> SpotifyAuthBase | None:
        return self._auth_manager

    @auth_manager.setter
    def auth_manager(self, auth_manager: SpotifyAuthBase | None):
        if auth_manager is not None:
            self._auth_manager = auth_manager
        else:
            self._auth_manager = (
                self.client_credentials_manager or self.oauth_manager
            )

    def __del__(self):
        """Make sure the connection (pool) gets closed"""
        if getattr(self, "_session", None) and isinstance(self._session, REQUESTS_SESSION):
            self._session.close()

    def _build_session(self):
        self._session = requests.Session()
        retry = Retry(
            total=self.retries,
            connect=None,
            read=False,
            allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE']),
            status=self.status_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=self.status_forcelist)

        adapter = HTTPAdapter(max_retries=retry)
        _ = self._session.mount('http://', adapter)
        _ = self._session.mount('https://', adapter)

    def _auth_headers(self):
        raise SpotifyNoAPIExceptionUnsupported

    def next(self, result):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ returns the next result given a paged result

            Parameters:
                - result - a previously returned paged result
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def previous(self, result):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ returns the previous result given a paged result

            Parameters:
                - result - a previously returned paged result
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def track(self, track_id: str, market: str | None = None) -> Track:
        """ returns a single track given the track's ID, URI or URL

            Parameters:
                - track_id - a spotify URI, URL or ID
                - market - an ISO 3166-1 alpha-2 country code.
        """

        if market != None:
            logger.warning(f"Market parameter is not supported. Not honoring market filter: {market}")

        trid = self._get_id("track", track_id)
        return NoAPI.get_track(trid)

    def tracks(self, tracks: list[str], market: str | None = None) -> list[Track]:
        """ returns a list of tracks given a list of track IDs, URIs, or URLs

            Parameters:
                - tracks - a list of spotify URIs, URLs or IDs. Maximum: 50 IDs.
                - market - an ISO 3166-1 alpha-2 country code.
        """

        if market != None:
            logger.warning(f"Market parameter is not supported. Not honoring market filter: {market}")

        tlist = [self._get_id("track", t) for t in tracks]
        return list(map(NoAPI.get_track, tlist))

    def artist(self, artist_id: str) -> Artist:
        """ returns a single artist given the artist's ID, URI or URL

            Parameters:
                - artist_id - an artist ID, URI or URL
        """

        trid = self._get_id("artist", artist_id)
        return NoAPI.get_artist(trid)

    def artists(self, artists: Iterable[str]) -> list[Artist]:
        """ returns a list of artists given the artist IDs, URIs, or URLs

            Parameters:
                - artists - a list of  artist IDs, URIs or URLs
        """

        tlist = [self._get_id("artist", a) for a in artists]
        return list(map(NoAPI.get_artist, tlist))

    def artist_albums(
        self, artist_id, album_type=None, include_groups=None, country=None, limit=20, offset=0  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
    ):
        """ Get Spotify catalog information about an artist's albums

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `artist_albums(..., include_groups='...')` instead.

            Parameters:
                - artist_id - the artist ID, URI or URL
                - include_groups - the types of items to return. One or more of 'album', 'single',
                                   'appears_on', 'compilation'. If multiple types are desired,
                                   pass in a comma separated string; e.g., 'album,single'.
                - country - limit the response to one particular country.
                - limit  - the number of albums to return
                - offset - the index of the first album to return
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def artist_top_tracks(self, artist_id, country="US"):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ Get Spotify catalog information about an artist's top 10 tracks
            by country.

            Currently unsupported. PRs welcome.

            Parameters:
                - artist_id - the artist ID, URI or URL
                - country - limit the response to one particular country.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def artist_related_artists(self, artist_id):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ Get Spotify catalog information about artists similar to an
            identified artist. Similarity is based on analysis of the
            Spotify community's listening history.

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - artist_id - the artist ID, URI or URL
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def album(self, album_id: str, market: str | None = None) -> Album:
        """ returns a single album given the album's ID, URIs or URL

            Parameters:
                - album_id - the album ID, URI or URL
                - market - an ISO 3166-1 alpha-2 country code
        """

        if market != None:
            logger.warning(f"Market parameter is not supported. Not honoring market filter: {market}")
        trid = self._get_id("album", album_id)
        return NoAPI.get_album(trid)

    def album_tracks(self, album_id: str, limit: int = 50, offset: int = 0, market: str | None = None):
        """ Get Spotify catalog information about an album's tracks

            Parameters:
                - album_id - the album ID, URI or URL
                - limit  - the number of items to return
                - offset - the index of the first item to return
                - market - an ISO 3166-1 alpha-2 country code.

        """

        if market != None:
            logger.warning(f"Market parameter is not supported. Not honoring market filter: {market}")

        trid = self._get_id("album", album_id)
        album = self.album(trid)
        return album.album_tracks(limit, offset)

    def albums(self, albums: str, market: str | None = None) -> list[Album]:
        """ returns a list of albums given the album IDs, URIs, or URLs

            Parameters:
                - albums - a list of  album IDs, URIs or URLs
                - market - an ISO 3166-1 alpha-2 country code
        """

        _ = market
        tlist = [self._get_id("album", a) for a in albums]
        return list(map(NoAPI.get_album, tlist))

    def show(self, show_id, market=None):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ returns a single show given the show's ID, URIs or URL

            Parameters:
                - show_id - the show ID, URI or URL
                - market - an ISO 3166-1 alpha-2 country code.
                           The show must be available in the given market.
                           If user-based authorization is in use, the user's country
                           takes precedence. If neither market nor user country are
                           provided, the content is considered unavailable for the client.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def shows(self, shows, market=None):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ returns a list of shows given the show IDs, URIs, or URLs

            Parameters:
                - shows - a list of show IDs, URIs or URLs
                - market - an ISO 3166-1 alpha-2 country code.
                           Only shows available in the given market will be returned.
                           If user-based authorization is in use, the user's country
                           takes precedence. If neither market nor user country are
                           provided, the content is considered unavailable for the client.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def show_episodes(self, show_id, limit=50, offset=0, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get Spotify catalog information about a show's episodes

            Parameters:
                - show_id - the show ID, URI or URL
                - limit  - the number of items to return
                - offset - the index of the first item to return
                - market - an ISO 3166-1 alpha-2 country code.
                           Only episodes available in the given market will be returned.
                           If user-based authorization is in use, the user's country
                           takes precedence. If neither market nor user country are
                           provided, the content is considered unavailable for the client.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def episode(self, episode_id, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ returns a single episode given the episode's ID, URIs or URL

            Parameters:
                - episode_id - the episode ID, URI or URL
                - market - an ISO 3166-1 alpha-2 country code.
                           The episode must be available in the given market.
                           If user-based authorization is in use, the user's country
                           takes precedence. If neither market nor user country are
                           provided, the content is considered unavailable for the client.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def episodes(self, episodes, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ returns a list of episodes given the episode IDs, URIs, or URLs

            Parameters:
                - episodes - a list of episode IDs, URIs or URLs
                - market - an ISO 3166-1 alpha-2 country code.
                           Only episodes available in the given market will be returned.
                           If user-based authorization is in use, the user's country
                           takes precedence. If neither market nor user country are
                           provided, the content is considered unavailable for the client.
        """

        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def search(self, q: str , limit: int = 10, offset: int = 0, type: str = "track", market: str | None = None) -> Search:  # pyright:ignore[reportUnusedParameter]
        """ searches for an item

            Parameters:
                - q - the search query (see how to write a query in the
                      official documentation https://developer.spotify.com/documentation/web-api/reference/search/)  # noqa
                - limit - the number of items to return (min = 1, default = 10, max = 50). The limit is applied
                          within each type, not on the total response.
                - offset - the index of the first item to return
                - type - the types of items to return. One or more of 'artist', 'album',
                         'track', 'playlist', 'show', and 'episode'.  If multiple types are desired,
                         pass in a comma separated string; e.g., 'track,album,episode'.
                - market - An ISO 3166-1 alpha-2 country code or the string
                           from_token.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def search_markets(self, q, limit=10, offset=0, type="track", markets=None, total=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ (experimental) Searches multiple markets for an item

            Parameters:
                - q - the search query (see how to write a query in the
                      official documentation https://developer.spotify.com/documentation/web-api/reference/search/)  # noqa
                - limit  - the number of items to return (min = 1, default = 10, max = 50). If a search is to be done on multiple
                            markets, then this limit is applied to each market. (e.g. search US, CA, MX each with a limit of 10).
                            If multiple types are specified, this applies to each type.
                - offset - the index of the first item to return
                - type - the types of items to return. One or more of 'artist', 'album',
                         'track', 'playlist', 'show', or 'episode'. If multiple types are desired, pass in a comma separated string.
                - markets - A list of ISO 3166-1 alpha-2 country codes. Search all country markets by default.
                - total - the total number of results to return across multiple markets and types.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def user(self, user):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets basic profile information about a Spotify User

            Parameters:
                - user - the id of the usr
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_playlists(self, limit=50, offset=0):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType]
        """ Get current user playlists without required getting his profile
            Parameters:
                - limit  - the number of items to return
                - offset - the index of the first item to return
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist(self, playlist_id: str, fields: str | None = None, market: str | None = None, _additional_types: Sequence[str] = ("track",)) -> Playlist:
        """ Gets playlist by id.

            Parameters:
                - playlist - the id of the playlist
                - fields - which fields to return
                - market - An ISO 3166-1 alpha-2 country code or the
                           string from_token.
                - additional_types - list of item types to return.
                                     valid types are: track and episode
        """
        if fields != None:
            logger.warning(f"Fields parameter is not supported. Not honoring fields filter: {fields}")

        if market != None:
            logger.warning(f"Market parameter is not supported. Not honoring market filter: {market}")

        if _additional_types != ("track",):
            logger.warning(f"Additional types parameter is not supported. Not honoring it: {_additional_types}")
        plid = self._get_id("playlist", playlist_id)
        return NoAPI.get_playlist(plid)

    def playlist_tracks(
        self,
        playlist_id: str,
        fields: str | None = None,
        limit: int = 100,
        offset: int = 0,
        market: str | None =None,
        additional_types: Sequence[str] = ("track",)
    ) -> list[Track]:
        """ Get full details of the tracks of a playlist.

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_items(playlist_id, ..., additional_types=('track',))` instead.

            Parameters:
                - playlist_id - the playlist ID, URI or URL
                - fields - which fields to return
                - limit - the maximum number of tracks to return
                - offset - the index of the first track to return
                - market - an ISO 3166-1 alpha-2 country code.
                - additional_types - list of item types to return.
                                     valid types are: track and episode
        """
        warnings.warn(
            "You should use `playlist_items(playlist_id, ...," +
            "additional_types=('track',))` instead",
            DeprecationWarning,
        )
        return self.playlist_items(playlist_id, fields, limit, offset,
                                   market, additional_types)

    def playlist_items(
        self,
        playlist_id: str,
        fields: str | None = None, limit: int = 100, offset: int = 0, market: str | None = None, additional_types: Sequence[str] =("track", "episode")  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ) -> list[Track]:
        """ Get full details of the tracks and episodes of a playlist.

            Parameters:
                - playlist_id - the playlist ID, URI or URL
                - fields - which fields to return
                - limit - the maximum number of tracks to return
                - offset - the index of the first track to return
                - market - an ISO 3166-1 alpha-2 country code.
                - additional_types - list of item types to return.
                                     valid types are: track and episode
        """
        plid = self._get_id("playlist", playlist_id)
        # TODO honor paging
        return NoAPI.get_playlist(plid).tracks

    def playlist_cover_image(self, playlist_id: str) -> Image:
        """ Get cover image of a playlist.

            Parameters:
                - playlist_id - the playlist ID, URI or URL
        """
        plid = self._get_id("playlist", playlist_id)
        return NoAPI.get_playlist(plid).images[0]

    def playlist_upload_cover_image(self, playlist_id, image_b64):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Replace the image used to represent a specific playlist

            Parameters:
                - playlist_id - the id of the playlist
                - image_b64 - image data as a Base64 encoded JPEG image string
                    (maximum payload size is 256 KB)
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist(self, user: str, playlist_id: str | None = None, fields: str | None = None, market: str | None = None):
        """ Gets a single playlist of a user

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist(playlist_id)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - fields - which fields to return
        """
        warnings.warn(
            "You should use `playlist(playlist_id)` instead",
            DeprecationWarning,
        )

        logger.warning(f"Not using user ({user}) parameter in call to user_playlist()")

        if playlist_id is None:
            raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible
        return self.playlist(playlist_id, fields=fields, market=market)

    def user_playlist_tracks(
        self,
        user=None, playlist_id=None, fields=None, limit=100, offset=0, market=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Get full details of the tracks of a playlist owned by a user.

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_tracks(playlist_id)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - fields - which fields to return
                - limit - the maximum number of tracks to return
                - offset - the index of the first track to return
                - market - an ISO 3166-1 alpha-2 country code.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def user_playlists(self, user, limit=50, offset=0):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets playlists of a user

            Parameters:
                - user - the id of the usr
                - limit  - the number of items to return
                - offset - the index of the first item to return
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def user_playlist_create(self, user, name, public=True, collaborative=False, description=""):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Creates a playlist for a user

            Parameters:
                - user - the id of the user
                - name - the name of the playlist
                - public - is the created playlist public
                - collaborative - is the created playlist collaborative
                - description - the description of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_change_details(
        self,
        user, playlist_id, name=None, public=None, collaborative=None, description=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Changes a playlist's name and/or public/private state

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_change_details(playlist_id, ...)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - name - optional name of the playlist
                - public - optional is the playlist public
                - collaborative - optional is the playlist collaborative
                - description - optional description of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_unfollow(self, user, playlist_id):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ This function is no longer in use, please use the recommended function in the warning!

            Unfollows (deletes) a playlist for a user

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `current_user_unfollow_playlist(playlist_id)` instead.

            Parameters:
                - user - the id of the user
                - name - the name of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_add_tracks(
        self, user, playlist_id, tracks, position=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Adds tracks to a playlist

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_add_items(playlist_id, tracks)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - a list of track URIs, URLs or IDs
                - position - the position to add the tracks
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_add_episodes(
        self, user, playlist_id, episodes, position=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Adds episodes to a playlist

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_add_items(playlist_id, episodes)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - episodes - a list of track URIs, URLs or IDs
                - position - the position to add the episodes
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_replace_tracks(self, user, playlist_id, tracks):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ This function is no longer in use, please use the recommended function in the warning!

            Replace all tracks in a playlist for a user

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_replace_items(playlist_id, tracks)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - the list of track ids to add to the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_reorder_tracks(
        self,
        user, playlist_id, range_start, insert_before, range_length=1, snapshot_id=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Reorder tracks in a playlist from a user

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_reorder_items(playlist_id, ...)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - range_start - the position of the first track to be reordered
                - range_length - optional the number of tracks to be reordered
                                 (default: 1)
                - insert_before - the position where the tracks should be
                                  inserted
                - snapshot_id - optional playlist's snapshot ID
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_remove_all_occurrences_of_tracks(
        self, user, playlist_id, tracks, snapshot_id=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Removes all occurrences of the given tracks from the given playlist

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_remove_all_occurrences_of_items(playlist_id, tracks)` instead.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - the list of track ids to remove from the playlist
                - snapshot_id - optional id of the playlist snapshot
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_remove_specific_occurrences_of_tracks(
        self, user, playlist_id, tracks, snapshot_id=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Removes specific occurrences of the given tracks from the given playlist

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - user - the id of the user
                - playlist_id - the id of the playlist
                - tracks - an array of objects containing Spotify URIs of the
                    tracks to remove with their current positions in the
                    playlist.  For example:
                        [  { "uri":"4iV5W9uYEdYUVa79Axb7Rh", "positions":[2] },
                        { "uri":"1301WleyT98MSxVHPZCA6M", "positions":[7] } ]
                - snapshot_id - optional id of the playlist snapshot
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_follow_playlist(self, playlist_owner_id, playlist_id):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ This function is no longer in use, please use the recommended function in the warning!

            Add the current authenticated user as a follower of a playlist.

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `current_user_follow_playlist(playlist_id)` instead.

            Parameters:
                - playlist_owner_id - the user id of the playlist owner
                - playlist_id - the id of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_playlist_is_following(
        self, playlist_owner_id, playlist_id, user_ids  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ This function is no longer in use, please use the recommended function in the warning!

            Check to see if the given users are following the given playlist

            .. deprecated::
            This method is deprecated and may be removed in a future version. Use
            `playlist_is_following(playlist_id, user_ids)` instead.

            Parameters:
                - playlist_owner_id - the user id of the playlist owner
                - playlist_id - the id of the playlist
                - user_ids - the ids of the users that you want to check to see
                    if they follow the playlist. Maximum: 5 ids.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def playlist_change_details(
        self,
        playlist_id, name=None, public=None, collaborative=None, description=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Changes a playlist's name and/or public/private state,
            collaborative state, and/or description

            Parameters:
                - playlist_id - the id of the playlist
                - name - optional name of the playlist
                - public - optional is the playlist public
                - collaborative - optional is the playlist collaborative
                - description - optional description of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_unfollow_playlist(self, playlist_id):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Unfollows (deletes) a playlist for the current authenticated
            user

            Parameters:
                - playlist_id - the id of the playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_add_items(
        self, playlist_id, items, position=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Adds tracks/episodes to a playlist

            Parameters:
                - playlist_id - the id of the playlist
                - items - a list of track/episode URIs or URLs
                - position - the position to add the tracks
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_replace_items(self, playlist_id, items):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Replace all tracks/episodes in a playlist

            Parameters:
                - playlist_id - the id of the playlist
                - items - list of track/episode ids to comprise playlist
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_reorder_items(self,
        playlist_id, range_start, insert_before, range_length=1, snapshot_id=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Reorder tracks in a playlist

            Parameters:
                - playlist_id - the id of the playlist
                - range_start - the position of the first track to be reordered
                - range_length - optional the number of tracks to be reordered
                                 (default: 1)
                - insert_before - the position where the tracks should be
                                  inserted
                - snapshot_id - optional playlist's snapshot ID
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_remove_all_occurrences_of_items(
        self, playlist_id, items, snapshot_id=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Removes all occurrences of the given tracks/episodes from the given playlist

            Parameters:
                - playlist_id - the id of the playlist
                - items - list of track/episode ids to remove from the playlist
                - snapshot_id - optional id of the playlist snapshot

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_remove_specific_occurrences_of_items(
        self, playlist_id, items, snapshot_id=None  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Removes all occurrences of the given tracks from the given playlist

            Parameters:
                - playlist_id - the id of the playlist
                - items - an array of objects containing Spotify URIs of the
                    tracks/episodes to remove with their current positions in
                    the playlist.  For example:
                        [  { "uri":"4iV5W9uYEdYUVa79Axb7Rh", "positions":[2] },
                        { "uri":"1301WleyT98MSxVHPZCA6M", "positions":[7] } ]
                - snapshot_id - optional id of the playlist snapshot
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_follow_playlist(self, playlist_id, public=True):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """
        Add the current authenticated user as a follower of a playlist.

        Parameters:
            - playlist_id - the id of the playlist

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def playlist_is_following(
            self, playlist_id: str, user_ids: list[str]  # pyright:ignore[reportUnusedParameter]
    ):
        """
        Check to see if the given users are following the given playlist

        Parameters:
            - playlist_id - the id of the playlist
            - user_ids - the ids of the users that you want to check to see
                if they follow the playlist. Maximum: 5 ids.

        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def me(self):
        """ Get detailed profile information about the current user.
            An alias for the 'current_user' method.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user(self):
        """ Get detailed profile information about the current user.
            An alias for the 'me' method.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_playing_track(self, market=None, additional_types=("track",)):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get information about the current users currently playing track.

            Parameters:
                - market - An ISO 3166-1 alpha-2 country code or the
                           string from_token.
                - additional_types - list of item types to return.
                                     valid types are: track and episode
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_albums(self, limit=20, offset=0, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets a list of the albums saved in the current authorized user's
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible
                - market - an ISO 3166-1 alpha-2 country code.

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_albums_add(self, albums):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Add one or more albums to the current user's
            "Your Music" library.
            Parameters:
                - albums - a list of album URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_albums_delete(self, albums):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Remove one or more albums from the current user's
            "Your Music" library.

            Parameters:
                - albums - a list of album URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_albums_contains(self, albums):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if one or more albums is already saved in
            the current Spotify user’s “Your Music” library.

            Parameters:
                - albums - a list of album URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_tracks(self, limit=20, offset=0, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets a list of the tracks saved in the current authorized user's
            "Your Music" library

            Parameters:
                - limit - the number of tracks to return
                - offset - the index of the first track to return
                - market - an ISO 3166-1 alpha-2 country code

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_tracks_add(self, tracks=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Add one or more tracks to the current user's
            "Your Music" library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_tracks_delete(self, tracks=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Remove one or more tracks from the current user's
            "Your Music" library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_tracks_contains(self, tracks=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if one or more tracks is already saved in
            the current Spotify user’s “Your Music” library.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_episodes(self, limit=20, offset=0, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets a list of the episodes saved in the current authorized user's
            "Your Music" library

            Parameters:
                - limit - the number of episodes to return
                - offset - the index of the first episode to return
                - market - an ISO 3166-1 alpha-2 country code

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_episodes_add(self, episodes=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Add one or more episodes to the current user's
            "Your Music" library.

            Parameters:
                - episodes - a list of episode URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_episodes_delete(self, episodes=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Remove one or more episodes from the current user's
            "Your Music" library.

            Parameters:
                - episodes - a list of episode URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_episodes_contains(self, episodes=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if one or more episodes is already saved in
            the current Spotify user’s “Your Music” library.

            Parameters:
                - episodes - a list of episode URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_shows(self, limit=20, offset=0, market=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets a list of the shows saved in the current authorized user's
            "Your Music" library

            Parameters:
                - limit - the number of shows to return
                - offset - the index of the first show to return
                - market - an ISO 3166-1 alpha-2 country code

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_shows_add(self, shows):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Add one or more albums to the current user's
            "Your Music" library.
            Parameters:
                - shows - a list of show URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_shows_delete(self, shows):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Remove one or more shows from the current user's
            "Your Music" library.

            Parameters:
                - shows - a list of show URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_saved_shows_contains(self, shows):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if one or more shows is already saved in
            the current Spotify user’s “Your Music” library.

            Parameters:
                - shows - a list of show URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_followed_artists(self, limit=20, after=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Gets a list of the artists followed by the current authorized user

            Parameters:
                - limit - the number of artists to return
                - after - the last artist ID retrieved from the previous
                          request

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_following_artists(self, ids=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if the current user is following certain artists

            Returns list of booleans respective to ids

            Parameters:
                - ids - a list of artist URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_following_users(self, ids=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Check if the current user is following certain users

            Returns list of booleans respective to ids

            Parameters:
                - ids - a list of user URIs, URLs or IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_top_artists(
        self, limit=20, offset=0, time_range="medium_term"  # pyright:ignore[reportUnusedParameter,reportMissingParameterType]
    ):
        """ Get the current user's top artists

            Parameters:
                - limit - the number of entities to return (max 50)
                - offset - the index of the first entity to return
                - time_range - Over what time frame are the affinities computed
                  Valid-values: short_term, medium_term, long_term
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_top_tracks(
        self, limit=20, offset=0, time_range="medium_term"  # pyright:ignore[reportUnusedParameter,reportMissingParameterType]
    ):
        """ Get the current user's top tracks

            Parameters:
                - limit - the number of entities to return
                - offset - the index of the first entity to return
                - time_range - Over what time frame are the affinities computed
                  Valid-values: short_term, medium_term, long_term
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_user_recently_played(self, limit=50, after=None, before=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get the current user's recently played tracks

            Parameters:
                - limit - the number of entities to return
                - after - unix timestamp in milliseconds. Returns all items
                          after (but not including) this cursor position.
                          Cannot be used if before is specified.
                - before - unix timestamp in milliseconds. Returns all items
                           before (but not including) this cursor position.
                           Cannot be used if after is specified
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_follow_artists(self, ids: list[str]):  # pyright:ignore[reportUnusedParameter]
        """ Follow one or more artists
            Parameters:
                - ids - a list of artist IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_follow_users(self, ids: list[str]):  # pyright:ignore[reportUnusedParameter]
        """ Follow one or more users
            Parameters:
                - ids - a list of user IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_unfollow_artists(self, ids: list[str]):  # pyright:ignore[reportUnusedParameter]
        """ Unfollow one or more artists
            Parameters:
                - ids - a list of artist IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def user_unfollow_users(self, ids: list[str]):  # pyright:ignore[reportUnusedParameter]
        """ Unfollow one or more users
            Parameters:
                - ids - a list of user IDs
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def featured_playlists(
        self, locale=None, country=None, timestamp=None, limit=20, offset=0  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Get a list of Spotify featured playlists

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - locale - The desired language, consisting of a lowercase ISO
                  639-1 alpha-2 language code and an uppercase ISO 3166-1 alpha-2
                  country code, joined by an underscore.

                - country - An ISO 3166-1 alpha-2 country code.

                - timestamp - A timestamp in ISO 8601 format:
                  yyyy-MM-ddTHH:mm:ss. Use this parameter to specify the user's
                  local time to get results tailored for that specific date and
                  time in the day

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def new_releases(self, country=None, limit=20, offset=0):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get a list of new album releases featured in Spotify

            Parameters:
                - country - An ISO 3166-1 alpha-2 country code.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def category(self, category_id, country=None, locale=None):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get info about a category

            Parameters:
                - category_id - The Spotify category ID for the category.

                - country - An ISO 3166-1 alpha-2 country code.
                - locale - The desired language, consisting of an ISO 639-1 alpha-2
                  language code and an ISO 3166-1 alpha-2 country code, joined
                  by an underscore.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def categories(self, country=None, locale=None, limit=20, offset=0):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get a list of categories

            Parameters:
                - country - An ISO 3166-1 alpha-2 country code.
                - locale - The desired language, consisting of an ISO 639-1 alpha-2
                  language code and an ISO 3166-1 alpha-2 country code, joined
                  by an underscore.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def category_playlists(
        self, category_id=None, country=None, limit=20, offset=0  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
    ):
        """ Get a list of playlists for a specific Spotify category

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - category_id - The Spotify category ID for the category.

                - country - An ISO 3166-1 alpha-2 country code.

                - limit - The maximum number of items to return. Default: 20.
                  Minimum: 1. Maximum: 50

                - offset - The index of the first item to return. Default: 0
                  (the first object). Use with limit to get the next set of
                  items.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def recommendations(self, seed_artists=None, seed_genres=None, seed_tracks=None,  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        limit=20, country=None, **kwargs):  # pyright:ignore[reportUnusedParameter,reportMissingParameterType,reportUnknownParameterType]
        """ Get a list of recommended tracks for one to five seeds.
            (at least one of `seed_artists`, `seed_tracks` and `seed_genres`
            are needed)

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - seed_artists - a list of artist IDs, URIs or URLs
                - seed_tracks - a list of track IDs, URIs or URLs
                - seed_genres - a list of genre names. Available genres for
                                recommendations can be found by calling
                                recommendation_genre_seeds

                - country - An ISO 3166-1 alpha-2 country code. If provided,
                            all results will be playable in this country.

                - limit - The maximum number of items to return. Default: 20.
                          Minimum: 1. Maximum: 100

                - min/max/target_<attribute> - For the tuneable track
                    attributes listed in the documentation, these values
                    provide filters and targeting on results.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def recommendation_genre_seeds(self):
        """ Get a list of genres available for the recommendations function.

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def audio_analysis(self, track_id: str):  # pyright:ignore[reportUnusedParameter]
        """ Get audio analysis for a track based upon its Spotify ID

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - track_id - a track URI, URL or ID
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def audio_features(self, tracks: str | list[str]):  # pyright:ignore[reportUnusedParameter]
        """ Get audio features for one or multiple tracks based upon their Spotify IDs

            .. deprecated::
            This endpoint has been removed by Spotify and is no longer available.

            Parameters:
                - tracks - a list of track URIs, URLs or IDs, maximum: 100 ids
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def devices(self):
        """ Get a list of user's available devices.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def current_playback(self, market=None, additional_types=None):  # pyright:ignore[reportUnusedParameter,reportUnknownParameterType,reportMissingParameterType]
        """ Get information about user's current playback.

            Parameters:
                - market - an ISO 3166-1 alpha-2 country code.
                - additional_types - `episode` to get podcast track information
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def currently_playing(self, market=None, additional_types=None):  # pyright:ignore[reportUnusedParameter,reportUnknownParameterType,reportMissingParameterType]
        """ Get user's currently playing track.

            Parameters:
                - market - an ISO 3166-1 alpha-2 country code.
                - additional_types - `episode` to get podcast track information
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def transfer_playback(self, device_id: str, force_play: bool = True):  # pyright:ignore[reportUnusedParameter]
        """ Transfer playback to another device.
            Note that the API accepts a list of device ids, but only
            actually supports one.

            Parameters:
                - device_id - transfer playback to this device
                - force_play - true: after transfer, play. false:
                               keep current state.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def start_playback(
            self, device_id: str | None = None, context_uri: str | None = None, uris: list[str] | None = None, offset: int | None = None, position_ms: int | None = None  # pyright:ignore[reportUnusedParameter]
    ):
        """ Start or resume user's playback.

            Provide a `context_uri` to start playback of an album,
            artist, or playlist.

            Provide a `uris` list to start playback of one or more
            tracks.

            Provide `offset` as {"position": <int>} or {"uri": "<track uri>"}
            to start playback at a particular offset.

            Parameters:
                - device_id - device target for playback
                - context_uri - spotify context uri to play
                - uris - spotify track uris
                - offset - offset into context by index or track
                - position_ms - (optional) indicates from what position to start playback.
                                Must be a positive number. Passing in a position that is
                                greater than the length of the track will cause the player to
                                start playing the next song.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def pause_playback(self, device_id: str | None =None):  # pyright:ignore[reportUnusedParameter]
        """ Pause user's playback.

            Parameters:
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def next_track(self, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Skip user's playback to next track.

            Parameters:
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def previous_track(self, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Skip user's playback to previous track.

            Parameters:
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def seek_track(self, position_ms: int, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Seek to position in current track.

            Parameters:
                - position_ms - position in milliseconds to seek to
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def repeat(self, state: str, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Set repeat mode for playback.

            Parameters:
                - state - `track`, `context`, or `off`
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def volume(self, volume_percent: int, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Set playback volume.

            Parameters:
                - volume_percent - volume between 0 and 100
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def shuffle(self, state: str, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Toggle playback shuffling.

            Parameters:
                - state - true or false
                - device_id - device target for playback
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def queue(self):
        """ Gets the current user's queue

            Unsupported. SpotNoAPI can not interact with user endpoints.
        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def add_to_queue(self, uri: str, device_id: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Adds a song to the end of a user's queue

            Unsupported. SpotNoAPI can not interact with user endpoints.

        """
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def available_markets(self) -> list[str]:
        """ Get the list of markets where Spotify is available.
            Returns a list of the countries in which Spotify is available, identified by their
            ISO 3166-1 alpha-2 country code with additional country codes for special territories.
        """
        return self.country_codes[:]  # This assumes we won't break anything by just acting as if all markets are available

    def _get_id(self, type: str, id: str) -> str:
        uri_match = re.search(Spotify._regex_spotify_uri, id)
        if uri_match is not None:
            uri_match_groups = uri_match.groupdict()
            if uri_match_groups['type'] != type:
                # TODO change to a ValueError in v3
                raise SpotifyException(400, -1, "Unexpected Spotify URI type.")
            return uri_match_groups['id']

        url_match = re.search(Spotify._regex_spotify_url, id)
        if url_match is not None:
            url_match_groups = url_match.groupdict()
            if url_match_groups['type'] != type:
                raise SpotifyException(400, -1, "Unexpected Spotify URL type.")
            # TODO change to a ValueError in v3
            return url_match_groups['id']

        # Raw identifiers might be passed, ensure they are also base-62
        if re.search(Spotify._regex_base62, id) is not None:
            return id

        # TODO change to a ValueError in v3
        raise SpotifyException(400, -1, "Unsupported URL / URI.")

    def _get_uri(self, type: str, id: str) -> str:
        if self._is_uri(id):
            return id
        else:
            return "spotify:" + type + ":" + self._get_id(type, id)

    def _is_uri(self, uri: str) -> bool:
        return re.search(Spotify._regex_spotify_uri, uri) is not None

    def _search_multiple_markets(self, q: str, limit: int, offset: int, type: str, markets: Sequence[str], total: int):  # pyright:ignore[reportUnusedParameter]
        raise SpotifyNoAPIExceptionUnsupportedProbablyImpossible

    def get_audiobook(self, id: str, market: str | None = None):  # pyright:ignore[reportUnusedParameter]
        """ Get Spotify catalog information for a single audiobook identified by its unique
        Spotify ID.

        Parameters:
        - id - the Spotify ID for the audiobook
        - market - an ISO 3166-1 alpha-2 country code.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def get_audiobooks(self, ids, market=None):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ Get Spotify catalog information for multiple audiobooks based on their Spotify IDs.

        Parameters:
        - ids - a list of Spotify IDs for the audiobooks
        - market - an ISO 3166-1 alpha-2 country code.
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome

    def get_audiobook_chapters(self, id, market=None, limit=20, offset=0):  # pyright:ignore[reportUnknownParameterType,reportUnusedParameter,reportMissingParameterType]
        """ Get Spotify catalog information about an audiobook’s chapters.

        Parameters:
        - id - the Spotify ID for the audiobook
        - market - an ISO 3166-1 alpha-2 country code.
        - limit - the maximum number of items to return
        - offset - the index of the first item to return
        """
        raise SpotifyNoAPIExceptionUnsupportedPRsWelcome
