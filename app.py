from flask import Flask, render_template, request, jsonify, session, redirect
import sqlite3
from flask_bcrypt import Bcrypt
import requests
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import googleapiclient.discovery
from functools import lru_cache
from collections import Counter

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

# --- Database Helpers ---
def get_db_connection():
    conn = sqlite3.connect('recommendations.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # NOTE: Use either block comment or separate line comment in CREATE statements
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

# --- Data Fetching & Recommendation Functions ---
def fetch_data(url, params=None, headers=None):
    """Fetch data from a given URL with optional parameters and headers."""
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {}

@lru_cache(maxsize=1)
def get_movie_genres():
    """Retrieve and cache movie genre IDs from TMDB."""
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

def recommend_images(query):
    """Fetch images from Unsplash based on query."""
    url = 'https://api.unsplash.com/search/photos'
    params = {
        'query': query,
        'client_id': UNSPLASH_ACCESS_KEY,
        'per_page': 10
    }
    data = fetch_data(url, params)
    results = []
    for img in data.get('results', []):
        results.append({
            'id': img['id'],
            'title': img.get('description') or 'No title available',
            'description': img.get('alt_description', 'No description available'),
            'image_url': img['urls']['regular'],
        })
    return results

def recommend_movies(query, person_search=False, genre_search=False, year=None):
    """Fetch movies from TMDB based on query, filtered by a person, genre, or year."""
    params = {'api_key': TMDB_API_KEY}
    url = None

    if person_search:
        # Search for a person (actor, director) by name
        person_url = 'https://api.themoviedb.org/3/search/person'
        person_data = fetch_data(person_url, {'api_key': TMDB_API_KEY, 'query': query.strip()})
        if person_data.get('results'):
            person_id = person_data['results'][0]['id']
            params['with_cast'] = person_id
            url = 'https://api.themoviedb.org/3/discover/movie'
        else:
            return [{'description': 'No person found'}]

    elif genre_search:
        # Search for a genre by name
        all_genres = get_movie_genres()
        if 'genres' in all_genres:
            genre_id = next((g['id'] for g in all_genres['genres'] 
                             if g['name'].lower() == query.lower()), None)
        else:
            genre_id = None
        if genre_id:
            params['with_genres'] = genre_id
            url = 'https://api.themoviedb.org/3/discover/movie'
        else:
            return [{'description': 'No genre found'}]

    else:
        # Search by movie title
        params['query'] = query.strip()
        url = 'https://api.themoviedb.org/3/search/movie'

    if year:
        params['primary_release_year'] = year.strip()

    data = fetch_data(url, params)
    results = []
    for movie in data.get('results', []):
        if movie.get('poster_path'):
            results.append({
                'id': movie['id'],
                'title': movie['title'],
                'description': movie.get('overview', 'No description available'),
                'image_url': f"https://image.tmdb.org/t/p/w500{movie['poster_path']}",
                'release_year': movie.get('release_date', 'Unknown')[:4]
            })
    return results

def recommend_videos(query, year=None):
    """Fetch videos from YouTube based on query and optionally filter by year."""
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'maxResults': 5,
        'key': YOUTUBE_API_KEY
    }
    if year:
        params['q'] = f"{query} {year}"

    try:
        req = youtube.search().list(**params)
        resp = req.execute()
        results = []
        for item in resp.get('items', []):
            video_id = item['id']['videoId']
            snippet = item['snippet']
            results.append({
                'id': video_id,
                'title': snippet['title'],
                'description': snippet.get('description', 'No description available'),
                'video_url': f"https://www.youtube.com/watch?v={video_id}",
                'thumbnail': snippet['thumbnails']['medium']['url']
            })
        return results
    except Exception as e:
        print(f"Error fetching YouTube videos: {e}")
        return []

def recommend_music(query, year=None):
    """
    Fetch music tracks from Spotify based on query and optionally filter by year.
    This does a simple search by track name.
    """
    search_query = f"{query} {year}" if year else query
    try:
        results = spotify.search(q=search_query, type='track', limit=5)
        tracks = []
        for t in results['tracks']['items']:
            tracks.append({
                'id': t['id'],
                'title': t['name'],
                'artist': ', '.join(a['name'] for a in t['artists']),
                'album': t['album']['name'],
                'thumbnail': t['album']['images'][1]['url'] if len(t['album']['images']) > 1 else '',
                'track_url': t['external_urls']['spotify']
            })
        return tracks
    except Exception as e:
        print(f"Error fetching music: {e}")
        return []

# --- Preference & Filtering Logic ---
def filter_out_disliked(results, content_type, username=None):
    """
    Filters out items that the user has disliked, if the user is logged in.
    """
    if not username:
        return results

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    if not user:
        conn.close()
        return results

    user_id = user['id']
    rows = conn.execute(
        'SELECT item_id FROM preferences WHERE user_id = ? AND content_type = ? AND preference = "dislike"',
        (user_id, content_type)
    ).fetchall()
    disliked_ids = {r['item_id'] for r in rows}
    conn.close()

    filtered = []
    for r in results:
        if str(r.get('id')) not in disliked_ids:
            filtered.append(r)
    return filtered

def get_user_liked_items(username):
    """
    Returns a dict of liked item IDs grouped by content_type:
    {
       'Movies': [id1, id2, ...],
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
    rows = conn.execute('''
        SELECT item_id, content_type
        FROM preferences
        WHERE user_id = ?
        AND preference = "like"
    ''', (user_id,)).fetchall()
    conn.close()

    data = {'Movies': [], 'Music': [], 'Videos': [], 'Images': []}
    for row in rows:
        data[row['content_type']].append(row['item_id'])
    return data

# --- AI/ML-Like Recommendation: Content-Based for Movies + Spotify Seeds for Music ---
def fetch_movie_details(movie_id):
    """Helper to fetch a single movie's details from TMDB."""
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

def fetch_spotify_track(track_id):
    """Helper to fetch a single track's details from Spotify."""
    try:
        return spotify.track(track_id)
    except:
        return None

def recommend_movies_by_genre_ids(genre_ids):
    """
    Given a list of genre IDs, fetch movies from TMDB that match those genres.
    We limit to 10 results to avoid overwhelming the user.
    """
    if not genre_ids:
        return []
    url = "https://api.themoviedb.org/3/discover/movie"
    params = {
        'api_key': TMDB_API_KEY,
        'with_genres': ",".join(map(str, genre_ids)),
        'sort_by': 'popularity.desc',
        'page': 1
    }
    data = fetch_data(url, params)
    results = []
    for m in data.get('results', [])[:10]:
        if m.get('poster_path'):
            results.append({
                'id': m['id'],
                'title': m['title'],
                'description': m.get('overview', 'No description available'),
                'image_url': f"https://image.tmdb.org/t/p/w500{m['poster_path']}",
                'release_year': m.get('release_date', 'Unknown')[:4]
            })
    return results

def recommend_music_via_spotify_seeds(track_ids):
    """
    Use Spotify's recommendation endpoint, providing up to 5 track seeds.
    """
    if not track_ids:
        return []
    # Spotify allows max 5 seeds
    seeds = track_ids[:5]
    try:
        recs = spotify.recommendations(seed_tracks=seeds, limit=10)
        results = []
        for t in recs['tracks']:
            results.append({
                'id': t['id'],
                'title': t['name'],
                'artist': ', '.join(a['name'] for a in t['artists']),
                'album': t['album']['name'],
                'thumbnail': t['album']['images'][1]['url'] if len(t['album']['images']) > 1 else '',
                'track_url': t['external_urls']['spotify']
            })
        return results
    except Exception as e:
        print(f"Error with Spotify recommendation seeds: {e}")
        return []

def generate_ai_recommendations(username):
    """
    A simple "AI" approach:
      - For Movies: Gather all liked movies, fetch their genre IDs, pick top 2 or 3 genres overall, then fetch new movies from TMDB by these genres.
      - For Music: Gather all liked track IDs, call Spotify's recommendation endpoint using them as seeds.
      - Filter out disliked items from final results.
    """
    if not username:
        return {'Movies': [], 'Music': []}

    # 1. Movies
    liked_data = get_user_liked_items(username)
    liked_movie_ids = liked_data['Movies']
    
    # Build a big list of genre IDs from user's liked movies
    all_genres = []
    for m_id in liked_movie_ids:
        details = fetch_movie_details(m_id)
        if details and details.get('genres'):
            for g in details['genres']:
                all_genres.append(g['id'])
    # Find the top few genres
    genre_count = Counter(all_genres)
    top_genres = [g for g, count in genre_count.most_common(3)]  # top 3 genres
    # Now recommend movies with these top genres
    recommended_movies = recommend_movies_by_genre_ids(top_genres)
    recommended_movies = filter_out_disliked(recommended_movies, 'Movies', username)

    # 2. Music
    liked_music_ids = liked_data['Music']
    recommended_tracks = recommend_music_via_spotify_seeds(liked_music_ids)
    recommended_tracks = filter_out_disliked(recommended_tracks, 'Music', username)

    return {
        'Movies': recommended_movies,
        'Music': recommended_tracks
    }

# ----------------
#       ROUTES
# ----------------
@app.route('/')
def index():
    """
    Show a fancy homepage with:
    - A search form
    - A grid of the user's liked items (Movies, Music, Videos, Images)
    - "AI" recommendations for Movies & Music
    """
    username = session.get('username')

    # Prepare data for UI
    liked_dict = get_user_liked_items(username) if username else None

    # Build final lists for each content type
    liked_movies = []
    liked_music = []
    liked_videos = []
    liked_images = []

    # If user is logged in, fetch the item details for each liked item
    if liked_dict:
        # Movies
        for mid in liked_dict['Movies']:
            mdata = fetch_movie_details(mid)
            if mdata and mdata.get('id'):
                liked_movies.append({
                    'id': mdata['id'],
                    'title': mdata['title'],
                    'description': mdata.get('overview', 'No description available'),
                    'image_url': f"https://image.tmdb.org/t/p/w500{mdata['poster_path']}" if mdata.get('poster_path') else '',
                    'release_year': mdata.get('release_date', '')[:4] if mdata.get('release_date') else ''
                })

        # Music
        for tid in liked_dict['Music']:
            track_info = fetch_spotify_track(tid)
            if track_info:
                liked_music.append({
                    'id': track_info['id'],
                    'title': track_info['name'],
                    'artist': ', '.join(a['name'] for a in track_info['artists']),
                    'album': track_info['album']['name'],
                    'thumbnail': track_info['album']['images'][1]['url'] if len(track_info['album']['images']) > 1 else '',
                    'track_url': track_info['external_urls']['spotify']
                })

        # Videos (YouTube)
        for vid in liked_dict['Videos']:
            try:
                detail_req = youtube.videos().list(part="snippet", id=vid)
                detail_resp = detail_req.execute()
                if detail_resp.get('items'):
                    snippet = detail_resp['items'][0]['snippet']
                    liked_videos.append({
                        'id': vid,
                        'title': snippet['title'],
                        'description': snippet.get('description', 'No description available'),
                        'video_url': f"https://www.youtube.com/watch?v={vid}",
                        'thumbnail': snippet['thumbnails']['medium']['url']
                    })
            except Exception as e:
                print(f"Error fetching YouTube video info: {e}")

        # Images (Unsplash)
        for img_id in liked_dict['Images']:
            # GET /photos/:id
            img_url = f"https://api.unsplash.com/photos/{img_id}"
            img_data = fetch_data(img_url, params={"client_id": UNSPLASH_ACCESS_KEY})
            if img_data.get('id'):
                liked_images.append({
                    'id': img_data['id'],
                    'title': img_data.get('description') or 'No title available',
                    'description': img_data.get('alt_description', 'No description available'),
                    'image_url': img_data['urls']['regular']
                })

    # AI/ML-lIke recommendations
    ai_recs = generate_ai_recommendations(username) if username else {'Movies': [], 'Music': []}

    return render_template('index.html',
                           liked_movies=liked_movies,
                           liked_music=liked_music,
                           liked_videos=liked_videos,
                           liked_images=liked_images,
                           ai_movie_recs=ai_recs['Movies'],
                           ai_music_recs=ai_recs['Music'])

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
            return jsonify({'message': 'Username already exists.'}), 400

        conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
        conn.commit()
        conn.close()

        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
            session['username'] = username
            return redirect('/')
        else:
            return jsonify({'message': 'Invalid username or password.'}), 401

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
        search_mode = request.form.get('search_mode', 'standard')
        year = request.form.get('year')

        if content_type == 'Movies':
            results = recommend_movies(query,
                                       person_search=(search_mode == 'person'),
                                       genre_search=(search_mode == 'genre'),
                                       year=year)
            results = filter_out_disliked(results, 'Movies', session.get('username'))
        elif content_type == 'Music':
            results = recommend_music(query, year=year)
            results = filter_out_disliked(results, 'Music', session.get('username'))
        elif content_type == 'Videos':
            results = recommend_videos(query, year=year)
            results = filter_out_disliked(results, 'Videos', session.get('username'))
        elif content_type == 'Images':
            results = recommend_images(query)
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

    # Remove any existing preference
    conn.execute(
        'DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?',
        (user_id, item_id, content_type)
    )
    # Insert like
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

    # Remove any existing preference
    conn.execute(
        'DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?',
        (user_id, item_id, content_type)
    )
    # Insert dislike
    conn.execute(
        'INSERT INTO preferences (user_id, item_id, content_type, preference) VALUES (?, ?, ?, ?)',
        (user_id, item_id, content_type, 'dislike')
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Disliked successfully!'})

if __name__ == '__main__':
    app.run(debug=True)
