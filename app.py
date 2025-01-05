from flask import Flask, render_template, request, jsonify
import requests
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import googleapiclient.discovery
from functools import lru_cache

app = Flask(__name__)

# API Keys and Configuration
SPOTIFY_CLIENT_ID = "a17439dd78c142038a430d130078e5e1"
SPOTIFY_CLIENT_SECRET = "d944ac83cb3d4c36bf6c8dd5d40f0d0a"
YOUTUBE_API_KEY = "AIzaSyCAbnABvXxdu4tWBt1SzxmKKnrwZ5TBOfE"
TMDB_API_KEY = "bf85dbf9edb4db205542289e2cb558da"
UNSPLASH_ACCESS_KEY = "FH9htZ9EowP41c2UgEiRbYeg1DSr3JNH16HN8cmaaXU"

# Spotify Setup
spotify_auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
spotify = spotipy.Spotify(client_credentials_manager=spotify_auth_manager)

# YouTube Service
youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

def fetch_data(url, params=None, headers=None):
    """ Fetch data from a given URL with optional parameters and headers. """
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {}

def get_genre_ids():
    """ Retrieve movie genre IDs from TMDB. """
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

def recommend_images(query):
    """ Fetch images from Unsplash based on query. """
    url = 'https://api.unsplash.com/search/photos'
    params = {
        'query': query,
        'client_id': UNSPLASH_ACCESS_KEY,
        'per_page': 10  # Number of images to fetch
    }
    data = fetch_data(url, params)
    results = []
    for img in data.get('results', []):
        results.append({
            'image_url': img['urls']['regular'],
            'description': img.get('alt_description', 'No description available')
        })
    return results


@lru_cache(maxsize=1)  # Cache the genre list for improved performance
def get_genre_ids():
    """ Retrieve movie genre IDs from TMDB. """
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

def recommend_movies(query, person_search=False, genre_search=False, year=None):
    """Fetch movies from TMDB based on query, filtered by a person, genre, or year."""
    # Base API parameters
    params = {'api_key': TMDB_API_KEY}

    if person_search:
        # Search for a person and fetch their ID
        person_url = 'https://api.themoviedb.org/3/search/person'
        person_params = {'api_key': TMDB_API_KEY, 'query': query.strip()}
        person_data = fetch_data(person_url, person_params)
        if person_data.get('results'):
            person_id = person_data['results'][0]['id']
            params['with_cast'] = person_id
        else:
            return [{'description': 'No person found'}]
        url = 'https://api.themoviedb.org/3/discover/movie'

    elif genre_search:
        # Search for a genre and fetch its ID
        genres = get_genre_ids()
        genre_id = next((genre['id'] for genre in genres['genres'] if genre['name'].lower() == query.lower()), None)
        if genre_id:
            params['with_genres'] = genre_id
        else:
            return [{'description': 'No genre found'}]
        url = 'https://api.themoviedb.org/3/discover/movie'

    else:
        # Default to searching for a movie by name
        params['query'] = query.strip()
        url = 'https://api.themoviedb.org/3/search/movie'

    # Add year filter if provided
    if year:
        if url == 'https://api.themoviedb.org/3/discover/movie':
            params['primary_release_year'] = year.strip()
        else:
            params['year'] = year.strip()

    # Fetch data from the TMDB API
    data = fetch_data(url, params)
    results = []
    for movie in data.get('results', []):
        if movie.get('poster_path'):
            results.append({
                'image_url': f"https://image.tmdb.org/t/p/w500{movie['poster_path']}",
                'title': movie['title'],
                'description': movie.get('overview', 'No description available'),
                'release_year': movie.get('release_date', 'Unknown')[:4]  # Extract year
            })
    return results


def recommend_videos(query, year=None):
    """ Fetch videos from YouTube based on query and optionally filter by year. """
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': 5,
        'key': YOUTUBE_API_KEY
    }
    if year:
        query += f" {year}"  # Append year to the query for filtering
        params['q'] = query

    try:
        request = youtube.search().list(**params)
        response = request.execute()
        results = []
        for item in response.get('items', []):
            video_id = item['id']['videoId']
            snippet = item['snippet']
            results.append({
                'video_url': f"https://www.youtube.com/watch?v={video_id}",
                'title': snippet['title'],
                'description': snippet.get('description', 'No description available'),
                'thumbnail': snippet['thumbnails']['medium']['url']
            })
        return results
    except Exception as e:
        print(f"Error fetching videos: {e}")
        return []
    
def recommend_music(query, year=None):
    """ Fetch music tracks from Spotify based on query and optionally filter by year. """
    search_query = query
    if year:
        search_query += f" {year}"  # Simulate year filtering by appending year to the query

    try:
        results = spotify.search(q=search_query, type='track', limit=5)
        tracks = []
        for track in results['tracks']['items']:
            tracks.append({
                'track_url': track['external_urls']['spotify'],
                'title': track['name'],
                'artist': ', '.join(artist['name'] for artist in track['artists']),
                'album': track['album']['name']
            })
        return tracks
    except Exception as e:
        print(f"Error fetching music: {e}")
        return []

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        query = request.form.get('query')
        content_type = request.form.get('content_type')
        search_mode = request.form.get('search_mode', 'standard')  # 'person', 'genre', or 'standard'
        year = request.form.get('year')  # Optional year filter

        if content_type == 'Movies':
            results = recommend_movies(
                query,
                person_search=(search_mode == 'person'),
                genre_search=(search_mode == 'genre'),
                year=year
            )
        elif content_type == 'Videos':
            results = recommend_videos(query, year=year)
        elif content_type == 'Music':
            results = recommend_music(query, year=year)
        elif content_type == 'Images':
            results = recommend_images(query)
        else:
            results = []  # Handle other content types if necessary

        return render_template('results.html', results=results, query=query, content_type=content_type, search_mode=search_mode, year=year)
    return render_template('index.html')



if __name__ == '__main__':
    app.run(debug=True)
