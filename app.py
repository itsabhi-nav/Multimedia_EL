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

# ------------------------------
# DATA FETCHING & RECOMMENDATION
# ------------------------------

def fetch_data(url, params=None, headers=None):
    """ Fetch data from a given URL with optional parameters and headers. """
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {}

def fetch_genre_ids():
    """ Retrieve movie genre IDs from TMDB without caching. """
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

@lru_cache(maxsize=1)
def get_genre_ids():
    """ Retrieve and cache movie genre IDs from TMDB. """
    return fetch_genre_ids()

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
            'id': img['id'],
            'image_url': img['urls']['regular'],
            'title': img.get('description') or 'No title available',
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
        if 'genres' in genres:
            genre_id = next((g['id'] for g in genres['genres'] 
                             if g['name'].lower() == query.lower()), None)
        else:
            genre_id = None

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

    data = fetch_data(url, params)
    results = []
    for movie in data.get('results', []):
        if movie.get('poster_path'):
            results.append({
                'id': movie['id'],
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
        query += f" {year}"
        params['q'] = query

    try:
        request = youtube.search().list(**params)
        response = request.execute()
        results = []
        for item in response.get('items', []):
            video_id = item['id']['videoId']
            snippet = item['snippet']
            results.append({
                'id': video_id,
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
        search_query += f" {year}"

    try:
        results = spotify.search(q=search_query, type='track', limit=5)
        tracks = []
        for track in results['tracks']['items']:
            tracks.append({
                'id': track['id'],
                'track_url': track['external_urls']['spotify'],
                'title': track['name'],
                'artist': ', '.join(artist['name'] for artist in track['artists']),
                'album': track['album']['name'],
                'thumbnail': track['album']['images'][1]['url'] if len(track['album']['images']) > 1 else ''
            })
        return tracks
    except Exception as e:
        print(f"Error fetching music: {e}")
        return []

# -------------------------------------------------
# FILTERING OUT DISLIKED ITEMS AND USER PREFERENCES
# -------------------------------------------------

def filter_out_disliked(results, content_type, username=None):
    """
    Filters out items the user has disliked, if the user is logged in.
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
    conn.close()

    disliked_ids = {row['item_id'] for row in disliked_items}

    filtered_results = []
    for result in results:
        # Convert the ID in result to string for comparison
        item_id = str(result.get('id', ''))
        # Skip disliked items
        if item_id in disliked_ids:
            continue
        filtered_results.append(result)

    return filtered_results

# ------------------------------------------------------------
# FETCHING LIKED ITEMS & GENERATING SIMILAR RECOMMENDATIONS
# ------------------------------------------------------------

def get_user_liked_items(username):
    """
    Returns a dictionary with lists of liked items for each content type:
    {
       'Movies': [...],
       'Music': [...],
       'Videos': [...],
       'Images': [...]
    }
    """
    if not username:
        return {'Movies': [], 'Music': [], 'Videos': [], 'Images': []}

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return {'Movies': [], 'Music': [], 'Videos': [], 'Images': []}

    user_id = user['id']

    # For each content type, fetch liked item_ids
    liked_items = conn.execute('''
        SELECT item_id, content_type
        FROM preferences
        WHERE user_id = ?
          AND preference = "like"
    ''', (user_id,)).fetchall()
    conn.close()

    # We'll store the IDs grouped by content_type
    liked_dict = {
        'Movies': [],
        'Music': [],
        'Videos': [],
        'Images': []
    }
    for row in liked_items:
        ctype = row['content_type']
        liked_dict[ctype].append(row['item_id'])

    return liked_dict


def fetch_movie_details(movie_id):
    """ Helper to get movie details by ID from TMDB. """
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

def fetch_similar_movies(movie_id):
    """ Returns a list of similar movies from TMDB for a given movie_id. """
    url = f"https://api.themoviedb.org/3/movie/{movie_id}/similar"
    params = {'api_key': TMDB_API_KEY, 'page': 1}
    data = fetch_data(url, params)
    results = []
    for movie in data.get('results', []):
        if movie.get('poster_path'):
            results.append({
                'id': movie['id'],
                'image_url': f"https://image.tmdb.org/t/p/w500{movie['poster_path']}",
                'title': movie['title'],
                'description': movie.get('overview', 'No description available'),
                'release_year': movie.get('release_date', 'Unknown')[:4]
            })
    return results

def generate_similar_recommendations(username):
    """
    Generates a list of recommended items based on what the user has liked.
    Currently only implements "similar movies" and naive approach for music.
    """
    if not username:
        return []

    # Step 1: Get user's liked items
    liked_dict = get_user_liked_items(username)

    recommended_results = []

    # --- Similar Movies ---
    for movie_id in liked_dict['Movies']:
        # Get similar movies
        similar_movies = fetch_similar_movies(movie_id)
        # Filter out disliked
        similar_movies = filter_out_disliked(similar_movies, 'Movies', username)
        recommended_results.extend(similar_movies)

    # --- Similar Music (Naive) ---
    for track_id in liked_dict['Music']:
        # We can fetch the track details from Spotify and re-run a search by track name
        try:
            track_info = spotify.track(track_id)
            track_name = track_info['name']
            # search using the track name
            similar_tracks = recommend_music(track_name, year=None)
            # Filter out disliked
            similar_tracks = filter_out_disliked(similar_tracks, 'Music', username)
            recommended_results.extend(similar_tracks)
        except Exception as e:
            print(f"Error fetching track info for ID {track_id}: {e}")

    # You could expand logic for Videos or Images similarly

    # Deduplicate recommended_results by ID
    unique_recs = {}
    for item in recommended_results:
        unique_recs[item['id']] = item

    # Convert back to a list
    final_recs = list(unique_recs.values())

    # Optionally limit how many results we show
    return final_recs[:10]  # Show top 10 combined similar recs

# -------------
# ROUTES
# -------------

@app.route('/')
def index():
    # Show user-liked items in separate rows, plus recommended items
    username = session.get('username', None)

    if username:
        liked_dict = get_user_liked_items(username)

        # For each content type, fetch the actual item details
        # so we can display them on the index page.
        liked_movies = []
        for movie_id in liked_dict['Movies']:
            movie_data = fetch_movie_details(movie_id)
            if movie_data and movie_data.get('id'):
                liked_movies.append({
                    'id': movie_data['id'],
                    'title': movie_data['title'],
                    'image_url': f"https://image.tmdb.org/t/p/w500{movie_data['poster_path']}" if movie_data.get('poster_path') else '',
                    'description': movie_data.get('overview', 'No description available'),
                    'release_year': movie_data.get('release_date', 'Unknown')[:4] if movie_data.get('release_date') else ''
                })

        # For Music, let's fetch track details
        liked_music = []
        for track_id in liked_dict['Music']:
            try:
                track_info = spotify.track(track_id)
                liked_music.append({
                    'id': track_info['id'],
                    'title': track_info['name'],
                    'artist': ', '.join(artist['name'] for artist in track_info['artists']),
                    'album': track_info['album']['name'],
                    'thumbnail': track_info['album']['images'][1]['url'] if len(track_info['album']['images']) > 1 else '',
                    'track_url': track_info['external_urls']['spotify']
                })
            except:
                pass

        # For Videos (YouTube), we can only show the ID
        liked_videos = []
        for video_id in liked_dict['Videos']:
            # We can do a naive approach: get snippet from YouTube
            try:
                detail_req = youtube.videos().list(part="snippet", id=video_id)
                detail_resp = detail_req.execute()
                if detail_resp.get('items'):
                    vid = detail_resp['items'][0]
                    snippet = vid['snippet']
                    liked_videos.append({
                        'id': video_id,
                        'title': snippet['title'],
                        'video_url': f"https://www.youtube.com/watch?v={video_id}",
                        'thumbnail': snippet['thumbnails']['medium']['url']
                    })
            except Exception as e:
                print(f"Error fetching YouTube video info: {e}")

        # For Images (Unsplash), we’ll store just the ID in DB.
        # We can fetch them again from the Unsplash API. But that
        # requires a "GET /photos/{id}" endpoint call. So let's do that:
        liked_images = []
        for img_id in liked_dict['Images']:
            # GET /photos/:id
            img_url = f"https://api.unsplash.com/photos/{img_id}"
            img_data = fetch_data(img_url, params={"client_id": UNSPLASH_ACCESS_KEY})
            if img_data.get('id'):
                liked_images.append({
                    'id': img_data['id'],
                    'title': img_data.get('description') or 'No title available',
                    'image_url': img_data['urls']['regular'],
                    'description': img_data.get('alt_description', 'No description available')
                })

        # Generate “recommended for you” based on liked items
        recommended_for_you = generate_similar_recommendations(username)

        return render_template('index.html',
                               liked_movies=liked_movies,
                               liked_music=liked_music,
                               liked_videos=liked_videos,
                               liked_images=liked_images,
                               recommended_for_you=recommended_for_you)
    else:
        # If user not logged in, just show the default index
        return render_template('index.html',
                               liked_movies=[],
                               liked_music=[],
                               liked_videos=[],
                               liked_images=[],
                               recommended_for_you=[])


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
            # Filter out disliked
            results = filter_out_disliked(results, 'Movies', session.get('username'))

        elif content_type == 'Videos':
            results = recommend_videos(query, year=year)
            # Filter out disliked
            results = filter_out_disliked(results, 'Videos', session.get('username'))

        elif content_type == 'Music':
            results = recommend_music(query, year=year)
            # Filter out disliked
            results = filter_out_disliked(results, 'Music', session.get('username'))

        elif content_type == 'Images':
            results = recommend_images(query)
            # Filter out disliked
            results = filter_out_disliked(results, 'Images', session.get('username'))

        else:
            results = []

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
    app.run(debug=True)
