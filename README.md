# spotNoAPI

##### spotNoAPI aims to be a scraping-based drop-in replacement for spotipy, a lightweight Python library for the [Spotify Web API](https://developer.spotify.com/documentation/web-api).

spotNoAPI does **not** aim to **fully** replace spotipy. See the [Features and Limitations](#features-and-limitations).

## Quick Start

You might be able to just specify as part of your dependencies,
that your spotipy installation is actually located at this repo,
or a cloned local version of it, and that's it.

As this project aims to be a drop-in replacement for spotipy, you can simply take a look at their documentation.
Keep in mind the limitations of spotNoAPI's approach though.

A full set of examples can be found in the [online documentation](http://spotipy.readthedocs.org/)
and in the [Spotipy examples directory](https://github.com/spotipy-dev/spotipy-examples).

## What is this for?

Using the Spotify Web API (SWA) comes at a cost. Quite literally.
To use the SWA, you need to create a Spotify Developer Account and register an app there.
This requires you to have a Spotify Premium Subscription.

Applications that depend on the SWA then need to distribute secrets to authenticate their app to their users.
This means that users of the app or library are rate-limited and the secrets distrubted might be misused by third parties which amplifies this problem.
FOSS projects that rely on the SWA usually circumvent this by passing the responsibility to create application credentials to the users,
which increases the barrier of entry for these applications, especially for more novice users.

While I see this as a general issue, with this project I only intend to solve a subset of that problem space.
Specifically, there are some applications which do not even need lots of information that is not already easily scrapeable,
like information about a specific track, album, artist or playlist.

Projects that for example mirror public Spotify playlists to different streaming services,
do not necessarily need many of the authenticated endpoints that the SWA provides.

## Features

My personal favourite feature:
Due to the responses you receive from these API calls not just being parsed json anymore,
the function no longer just return `Any`.
Instead I built special data types,
that are fully typed and can still be used via the `__getitem__` operator (`["item"]`).

**TYPE HINTS 4 EVER!!!**

Moving to what is actually supported,
I'm currently mostly just implementing the calls that I actually need
and that are easy to implement.

So far this is:
- `track()`, `tracks()`
- `artist()`, `artists()`
- `album()`, `albums()`
- `album_tracks()`

## Limitations

Basically everything else does not work.

I'm thinking about implementing `search()`,
but I think you'd have to do scraping with a browser backend.
So that means using selenium, for example, and these setups
are usually easy to break in my experience.

## How does it work?

Did you ever share a spotify link and observed
how it already gave you a little preview in the chat app you were using?
This is done using the [Open Graph Protocol](https://ogp.me/).
It basicaly just specifies that there are these helpful little `<meta>` tags
in the `<head>` of a website which help apps generate a preview for that site.
And they have quite a bit of information inside them,
or at least enough to feed most of this library.

So when you call `artist("https://open.spotify.com/artist/6PfSUFtkMVoDkx4MQkzOi3")`
or even just `artist("6R1kfr0GIWnwxY4zW11Vag")`, this library will send
a request to the specified artist page, collect the information mostly contained
in these `<meta>` tags and build a fake Web API response based on it.

## License

Note that this Project is a fork of spotipy (the last spotipy commit was `c52a29f6d255c8f1b9b0ff5c2ebf566174db2cb5`).
Up to that commit, the code was licensed under the MIT License (see the `LICENSE.spotipy.md`)

I decided to relicense my fork under AGPLv3 (see `LICENSE.md`).
If you use this project, please make sure you know your rights and duties.

