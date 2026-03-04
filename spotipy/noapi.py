# spotNoAPI: Copyright (c) 2026 Merlin Sievers (AGPLv3)

""" None of my homies use the API """

from functools import cache
from collections.abc import Iterable
from dataclasses import dataclass, field
import logging
from typing import Any, ClassVar, override

from bs4 import BeautifulSoup, Tag
from bs4.element import PageElement
import requests

from spotipy.exceptions import SpotifyNoAPIException

SPOTIFY_BASE_URL: str = 'https://open.spotify.com'


# Should inherit dict, so isinstance(sth, dict) checks work
@dataclass
class Base(dict):  # pyright:ignore[reportMissingTypeArgument]

    @override
    def __getitem__(self, key: str) -> Any:  # pyright:ignore[reportAny,reportExplicitAny]
        return getattr(self, key)  # pyright:ignore[reportAny]

    @override
    def get(self, key: str, default: Any = None) -> Any:  # pyright:ignore[reportAny,reportExplicitAny]
        return getattr(self, key, default)  # pyright:ignore[reportAny]


@dataclass
class SpotifyBase(Base):
    id: str
    type: ClassVar[str]

    @property
    def uri(self) -> str:
        return f'spotify:{self.type}:{self.id}'


@dataclass
class Image(Base):
    url: str
    width: int = 640  # currently always 640x640 (sample size of 1)
    height: int = 640


@dataclass
class Artist(SpotifyBase):
    type: ClassVar[str] = 'artist'
    name: str
    genres: list[str] = field(default_factory=list)


@dataclass
class AlbumTracks(Base):
    track_ids: list[str]
    limit: int
    offset: int

    @property
    def items(self) -> list["Track"]:
        return list(map(NoAPI.get_track, self.track_ids))

    @property
    def next(self) -> list["Track"]:
        return []


@dataclass
class Album(SpotifyBase):
    type: ClassVar[str] = 'album'
    name: str
    artist_ids: list[str]
    track_ids: list[str]
    release_date: str
    album_type: str
    images: list[Image]
    label: str = ""
    copyrights: str = ""  # TODO parse this
    genres: list[str] = field(default_factory=list)

    @property
    def total_tracks(self) -> int:
        return len(self.track_ids)

    @property
    def artists(self) -> Iterable[Artist]:
        return list(map(NoAPI.get_artist, self.artist_ids))

    @property
    def tracks(self) -> AlbumTracks:
        return self.album_tracks(1000, 0)
        # return list(map(NoAPI.get_track, self.track_ids))

    def album_tracks(self, limit: int, offset: int) -> AlbumTracks:
        return AlbumTracks(self.track_ids, limit, offset)


@dataclass
class Track(SpotifyBase):
    type: ClassVar[str] = 'track'
    name: str
    artist_ids: list[str]
    album_id: str
    duration_ms: int
    track_number: int
    disc_number: int = 0
    explicit: bool = False
    popularity: int = 100


    @property
    def external_urls(self) -> dict[str, str]:
        return {
            'spotify': f"{SPOTIFY_BASE_URL}/track/{self.id}",
        }

    @property
    def album(self) -> Album:
        return NoAPI.get_album(self.album_id)

    @property
    def artists(self) -> Iterable[Artist]:
        return list(map(NoAPI.get_artist, self.artist_ids))


@dataclass
class Playlist(SpotifyBase):
    type: ClassVar[str] = 'playlist'
    name: str
    description: str
    track_ids: list[str]

    @property
    def tracks(self) -> Iterable[Track]:
        return list(map(NoAPI.get_track, self.track_ids))


@dataclass
class Search(Base):
    track_ids: list[str]
    album_ids: list[str]
    artist_ids: list[str]
    playlist_ids: list[str]


    @property
    def tracks(self) -> Iterable[Track]:
        return list(map(NoAPI.get_track, self.track_ids))

    @property
    def albums(self) -> Iterable[Album]:
        return list(map(NoAPI.get_album, self.album_ids))

    @property
    def artists(self) -> Iterable[Artist]:
        return list(map(NoAPI.get_artist, self.artist_ids))

    @property
    def playlists(self) -> Iterable[Playlist]:
        return list(map(NoAPI.get_playlist, self.playlist_ids))



class NoAPI():
    @cache
    @staticmethod
    def _get_soup(uri: str) -> BeautifulSoup:
        logging.debug(f"Fetching: {uri}")
        resp = requests.get(uri)
        if not resp.ok:
            raise Exception(f'Failed to get uri "{uri}" - status code: {resp.status_code}')
        return BeautifulSoup(resp.text, 'html.parser')

    @staticmethod
    def _get_meta(soup: BeautifulSoup, name: str, key: str = 'name') -> str:
        elem = soup.find(attrs={key: name})
        if not elem:
            raise Exception(f'Could not find meta element {key}: {name} in soup.')
        return NoAPI._get_content(elem)

    @staticmethod
    def _get_content(elem: PageElement) -> str:
        if isinstance(elem, Tag):
            return str(elem.get('content'))
        return elem.get_text()

    @staticmethod
    def _uri_to_id(uri: str) -> tuple[str, str]:
        parts = uri.split('/')
        return (parts[-2], parts[-1])

    @cache
    @staticmethod
    def get_artist(artist_id: str) -> Artist:
        try:
            uri = f'{SPOTIFY_BASE_URL}/artist/{artist_id}'
            soup = NoAPI._get_soup(uri)
            if not soup.head:
                raise SpotifyNoAPIException(f'Could not even get a head when fetching soup for {uri}.')
            title = NoAPI._get_meta(soup, 'og:title', 'property')
            return Artist(
                id = artist_id,
                name = title
            )
        except Exception as e:
            raise SpotifyNoAPIException(f'Could not get artist with id {artist_id}: {e}')

    @cache
    @staticmethod
    def get_track(track_id: str) -> Track:
        try:
            uri = f'{SPOTIFY_BASE_URL}/track/{track_id}'
            soup = NoAPI._get_soup(uri)
            name = NoAPI._get_meta(soup, 'og:title', 'property')
            artist_ids = list(map(
                lambda x: x[1],
                map(
                    NoAPI._uri_to_id,
                    map(
                        NoAPI._get_content,
                        soup.find_all(attrs={'name': 'music:musician'})
                    )
                )
            ))
            album_id = NoAPI._uri_to_id(NoAPI._get_meta(soup, 'music:album'))[1]
            duration_ms = int(NoAPI._get_meta(soup, 'music:duration')) * 1000
            track_number = int(NoAPI._get_meta(soup, 'music:album:track'))
            return Track(
                id = NoAPI._uri_to_id(uri)[1],
                name = name,
                artist_ids = artist_ids,
                duration_ms = duration_ms,
                track_number = track_number,
                album_id = album_id
            )
        except Exception as e:
            raise SpotifyNoAPIException(f'Could not get track with id {track_id}: {e}')

    @cache
    @staticmethod
    def get_album(album_id: str) -> Album:
        try:
            uri = f'{SPOTIFY_BASE_URL}/album/{album_id}'
            soup = NoAPI._get_soup(uri)
            title = NoAPI._get_meta(soup, 'og:title', 'property')
            if not soup.head:
                raise SpotifyNoAPIException(f'Could not even get a head when fetching soup for {uri}.')
            results = soup.head.find_all(attrs={'name': 'music:musician'})
            artist_ids = list(map(lambda x: NoAPI._uri_to_id(NoAPI._get_content(x))[1], results))
            results = soup.head.find_all(attrs={'name': 'music:song'})
            track_ids = list(map(lambda x: NoAPI._uri_to_id(NoAPI._get_content(x))[1], results))
            release_date = NoAPI._get_meta(soup, 'music:release_date', 'name')
            description = NoAPI._get_meta(soup, 'og:description', 'property')
            album_type = description.split(' · ')[1]
            image_url = NoAPI._get_meta(soup, 'og:image', 'property')
            return Album(
                id = NoAPI._uri_to_id(uri)[1],
                name = title,
                artist_ids = artist_ids,
                track_ids = track_ids,
                release_date = release_date,
                album_type = album_type,
                images = [ Image(image_url) ],
            )
        except Exception as e:
            raise SpotifyNoAPIException(f'Could not get track with id {album_id}: {e}')

    @cache
    @staticmethod
    def get_playlist(playlist_id: str) -> Playlist:
        try:
            uri = f'{SPOTIFY_BASE_URL}/playlist/{playlist_id}'
            soup = NoAPI._get_soup(uri)
            if not soup.head:
                raise SpotifyNoAPIException(f'Could not even get a head when fetching soup for {uri}.')
            results = soup.head.find_all(attrs={'name': 'music:song'})
            tracklist = list(map(lambda x: NoAPI._uri_to_id(NoAPI._get_content(x))[1], results))
            title = NoAPI._get_meta(soup, 'og:title', 'property')
            description = NoAPI._get_meta(soup, 'og:description', 'property')
            return Playlist(
                id = NoAPI._uri_to_id(uri)[1],
                name = title,
                description = description,
                track_ids = tracklist
            )
        except Exception as e:
            raise SpotifyNoAPIException(f'Could not get track with id {playlist_id}: {e}')

    @staticmethod
    def search(query: str, type: str) -> Search:
        # TODO Implement this
        _ = query
        _ = type
        return Search([], [], [], [])
