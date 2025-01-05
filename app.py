from flask import Flask, render_template, request, jsonify, session, redirect
import sqlite3
from flask_bcrypt import Bcrypt
import requests
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import googleapiclient.discovery
from functools import lru_cache

# Flask app setup
app = Flask(__name__)
app.secret_key = 'your_secret_key'
bcrypt = Bcrypt(app)

# API keys and configurations
SPOTIFY_CLIENT_ID = "a17439dd78c142038a430d130078e5e1"
SPOTIFY_CLIENT_SECRET = "d944ac83cb3d4c36bf6c8dd5d40f0d0a"
YOUTUBE_API_KEY = "AIzaSyCAbnABvXxdu4tWBt1SzxmKKnrwZ5TBOfE"
TMDB_API_KEY = "bf85dbf9edb4db205542289e2cb558da"
UNSPLASH_ACCESS_KEY = "FH9htZ9EowP41c2UgEiRbYeg1DSr3JNH16HN8cmaaXU"

# Spotify and YouTube setup
spotify_auth_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)
spotify = spotipy.Spotify(client_credentials_manager=spotify_auth_manager)
youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# Database helper
def get_db_connection():
    conn = sqlite3.connect('recommendations.db')
    conn.row_factory = sqlite3.Row
    return conn

# Initialize the database
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Preferences table
    # NOTE: Use either a block comment or place the comment on its own line
    # because SQLite may reject inline comments in a CREATE TABLE statement.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            preference TEXT NOT NULL, 
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- FIX 1: Rename the first (non-cached) get_genre_ids to fetch_genre_ids ---

def fetch_genre_ids():
    """ Retrieve movie genre IDs from TMDB without caching. """
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

@lru_cache(maxsize=1)  # Cache the genre list for improved performance
def get_genre_ids():
    """ Retrieve movie genre IDs from TMDB with caching. """
    return fetch_genre_ids()

# Recommendation functions
def fetch_data(url, params=None, headers=None):
    """ Fetch data from a given URL with optional parameters and headers. """
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {}

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
            'id': img['id'],  # Ensure we have an ID for like/dislike
            'image_url': img['urls']['regular'],
            'description': img.get('alt_description', 'No description available')
        })
    return results

def recommend_movies(query, person_search=False, genre_search=False, year=None):
    """Fetch movies from TMDB based on query, filtered by a person, genre, or year."""
    params = {'api_key': TMDB_API_KEY}

    if person_search:
        # Search for a person and get their ID
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
        # Search for a genre and get its ID
        genres = get_genre_ids()
        genre_id = next((g['id'] for g in genres['genres'] 
                         if g['name'].lower() == query.lower()), None)
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
        params['primary_release_year'] = year.strip()

    # Fetch data and process results
    data = fetch_data(url, params)
    results = []
    for movie in data.get('results', []):
        if movie.get('poster_path'):
            results.append({
                'id': movie['id'],  # Ensure we have an ID
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
                'id': video_id,  # Ensure we have an ID
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
                'id': track['id'],  # Ensure we have an ID
                'track_url': track['external_urls']['spotify'],
                'title': track['name'],
                'artist': ', '.join(artist['name'] for artist in track['artists']),
                'album': track['album']['name'],
                'thumbnail': track['album']['images'][1]['url']  # Medium-sized album image
            })
        return tracks
    except Exception as e:
        print(f"Error fetching music: {e}")
        return []

# Filter recommendations based on preferences
def filter_recommendations(results, content_type, username=None):
    """
    Example filtering function (currently not explicitly called).
    It demonstrates how to filter out disliked items and prioritize liked ones.
    """
    if not username:
        return results  # If user not logged in, return everything

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    
    # If user doesn't exist (edge case), return results unfiltered
    if not user:
        conn.close()
        return results

    user_id = user['id']
    disliked_items = conn.execute(
        'SELECT item_id FROM preferences WHERE user_id = ? AND content_type = ? AND preference = "dislike"',
        (user_id, content_type)
    ).fetchall()
    liked_items = conn.execute(
        'SELECT item_id FROM preferences WHERE user_id = ? AND content_type = ? AND preference = "like"',
        (user_id, content_type)
    ).fetchall()
    conn.close()

    disliked_ids = {row['item_id'] for row in disliked_items}
    liked_ids = {row['item_id'] for row in liked_items}

    filtered_results = []
    for result in results:
        # Convert the ID in result to string for comparison
        item_id = str(result['id'])

        # Skip disliked items
        if item_id in disliked_ids:
            continue

        # Mark liked items with higher priority
        if item_id in liked_ids:
            result['priority'] = 1
        filtered_results.append(result)

    # Sort by priority if present (higher first)
    return sorted(filtered_results, key=lambda x: x.get('priority', 0), reverse=True)

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if user:
            conn.close()
            return jsonify({'message': 'Username already exists. Please choose another.'}), 400

        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
        conn.commit()
        conn.close()

        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = username
            return redirect('/')
        else:
            return jsonify({'message': 'Invalid username or password. Please try again.'}), 401

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect('/')

@app.route('/recommend', methods=['POST'])
def recommend():
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

        # Optionally filter based on user preferences (uncomment to apply):
        # results = filter_recommendations(results, content_type, session.get('username'))

        return render_template('results.html', 
                               results=results, 
                               query=query, 
                               content_type=content_type, 
                               search_mode=search_mode, 
                               year=year)

    return render_template('index.html')

@app.route('/like', methods=['POST'])
def like():
    username = session.get('username')
    if not username:
        return jsonify({'message': 'You need to be logged in to like items.'}), 403

    item_id = request.json.get('item_id')
    content_type = request.json.get('content_type')

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'message': 'User does not exist.'}), 400

    user_id = user['id']

    # Remove any existing preference for this item
    conn.execute(
        'DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?',
        (user_id, item_id, content_type)
    )

    # Add a "like"
    conn.execute(
        'INSERT INTO preferences (user_id, item_id, content_type, preference) VALUES (?, ?, ?, ?)',
        (user_id, item_id, content_type, 'like')
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Liked successfully!'})

@app.route('/dislike', methods=['POST'])
def dislike():
    username = session.get('username')
    if not username:
        return jsonify({'message': 'You need to be logged in to dislike items.'}), 403

    item_id = request.json.get('item_id')
    content_type = request.json.get('content_type')

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'message': 'User does not exist.'}), 400

    user_id = user['id']

    # Remove any existing preference for this item
    conn.execute(
        'DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?',
        (user_id, item_id, content_type)
    )

    # Add a "dislike"
    conn.execute(
        'INSERT INTO preferences (user_id, item_id, content_type, preference) VALUES (?, ?, ?, ?)',
        (user_id, item_id, content_type, 'dislike')
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Disliked successfully!'})

# Run the app
if __name__ == '__main__':
    # Make sure to create 'templates' folder with index.html, register.html,
    # login.html, and results.html for the render_template calls.
    app.run(debug=True)
