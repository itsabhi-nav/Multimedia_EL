from flask import Flask, render_template, request, jsonify, session, redirect
import sqlite3
from flask_bcrypt import Bcrypt
import requests
from spotipy.oauth2 import SpotifyClientCredentials
import spotipy
import googleapiclient.discovery
from functools import lru_cache
from collections import Counter

app = Flask(__name__)
app.secret_key = 'YOUR_SECRET_KEY'  # Replace with something more secure in production
bcrypt = Bcrypt(app)

# -------------------------
# API KEYS AND CONFIG
# -------------------------
SPOTIFY_CLIENT_ID = "a17439dd78c142038a430d130078e5e1"
SPOTIFY_CLIENT_SECRET = "d944ac83cb3d4c36bf6c8dd5d40f0d0a"
YOUTUBE_API_KEY = "AIzaSyCAbnABvXxdu4tWBt1SzxmKKnrwZ5TBOfE"
TMDB_API_KEY = "bf85dbf9edb4db205542289e2cb558da"
UNSPLASH_ACCESS_KEY = "FH9htZ9EowP41c2UgEiRbYeg1DSr3JNH16HN8cmaaXU"

# -------------------------
# SPOTIFY & YOUTUBE
# -------------------------
spotify_auth_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)
spotify = spotipy.Spotify(client_credentials_manager=spotify_auth_manager)
youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

# -------------------------
# DATABASE HELPER
# -------------------------
def get_db_connection():
    conn = sqlite3.connect('recommendations.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    # Users table
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    # Preferences table
    c.execute('''
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

# -------------------------
# DATA FETCHING
# -------------------------
def fetch_data(url, params=None, headers=None):
    try:
        resp = requests.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return {}

@lru_cache(maxsize=1)
def get_movie_genres():
    """Retrieve & cache movie genre IDs from TMDB."""
    url = "https://api.themoviedb.org/3/genre/movie/list"
    params = {'api_key': TMDB_API_KEY}
    return fetch_data(url, params)

# -------------------------
# RECOMMENDATION FUNCTIONS
# -------------------------
def recommend_images(query):
    """Fetch images from Unsplash."""
    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "client_id": UNSPLASH_ACCESS_KEY,
        "per_page": 10
    }
    data = fetch_data(url, params)
    results = []
    for img in data.get("results", []):
        results.append({
            "id": img["id"],
            "title": img.get("description") or "No title",
            "description": img.get("alt_description", "No description"),
            "image_url": img["urls"]["regular"]
        })
    return results

def recommend_movies(query, person_search=False, genre_search=False, year=None):
    """Fetch movies from TMDB."""
    params = {"api_key": TMDB_API_KEY}
    url = None

    if person_search:
        person_url = "https://api.themoviedb.org/3/search/person"
        person_data = fetch_data(person_url, {"api_key": TMDB_API_KEY, "query": query.strip()})
        if person_data.get("results"):
            person_id = person_data["results"][0]["id"]
            params["with_cast"] = person_id
            url = "https://api.themoviedb.org/3/discover/movie"
        else:
            return [{"description": "No person found"}]
    elif genre_search:
        all_genres = get_movie_genres()
        if 'genres' in all_genres:
            genre_id = next((g['id'] for g in all_genres['genres']
                             if g['name'].lower() == query.lower()), None)
        else:
            genre_id = None
        if genre_id:
            params['with_genres'] = genre_id
            url = "https://api.themoviedb.org/3/discover/movie"
        else:
            return [{"description": "No genre found"}]
    else:
        params["query"] = query.strip()
        url = "https://api.themoviedb.org/3/search/movie"

    if year:
        params["primary_release_year"] = year.strip()

    data = fetch_data(url, params)
    results = []
    for m in data.get("results", []):
        if m.get("poster_path"):
            results.append({
                "id": m["id"],
                "title": m["title"],
                "description": m.get("overview", "No description"),
                "image_url": f"https://image.tmdb.org/t/p/w500{m['poster_path']}",
                "release_year": m.get("release_date", "Unknown")[:4]
            })
    return results

def recommend_videos(query, year=None):
    """Fetch videos from YouTube."""
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
        for item in resp.get("items", []):
            vid_id = item["id"]["videoId"]
            snippet = item["snippet"]
            results.append({
                "id": vid_id,
                "title": snippet["title"],
                "description": snippet.get("description", "No description"),
                "video_url": f"https://www.youtube.com/watch?v={vid_id}",
                "thumbnail": snippet["thumbnails"]["medium"]["url"]
            })
        return results
    except Exception as e:
        print(f"Error fetching YouTube videos: {e}")
        return []

def recommend_music(query, year=None):
    """Fetch music tracks from Spotify by textual query."""
    search_query = f"{query} {year}" if year else query
    try:
        res = spotify.search(q=search_query, type='track', limit=5)
        tracks = []
        for t in res['tracks']['items']:
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

# -------------------------
# FILTER & PREFERENCES
# -------------------------
def filter_out_disliked(results, content_type, username=None):
    """Remove items the user has disliked."""
    if not username:
        return results
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return results

    user_id = user["id"]
    disliked_rows = conn.execute(
        "SELECT item_id FROM preferences WHERE user_id = ? AND content_type = ? AND preference = 'dislike'",
        (user_id, content_type)
    ).fetchall()
    disliked_ids = {row["item_id"] for row in disliked_rows}
    conn.close()

    filtered = []
    for r in results:
        if str(r.get("id")) not in disliked_ids:
            filtered.append(r)
    return filtered

def get_user_liked_items(username):
    """Return a dict of liked items grouped by content_type."""
    if not username:
        return {'Movies': [], 'Music': [], 'Videos': [], 'Images': []}

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return {'Movies': [], 'Music': [], 'Videos': [], 'Images': []}

    user_id = user["id"]
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

# -------------------------
# AI RECOMMENDATIONS
# -------------------------
def fetch_movie_details(movie_id):
    """Get movie details by ID from TMDB."""
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    return fetch_data(url, {"api_key": TMDB_API_KEY})

def fetch_spotify_track(track_id):
    """Get track details by ID from Spotify."""
    try:
        return spotify.track(track_id)
    except:
        return None

def recommend_movies_by_genre_ids(genre_ids):
    """Recommend movies from top genres."""
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
                'description': m.get('overview', 'No description'),
                'image_url': f"https://image.tmdb.org/t/p/w500{m['poster_path']}",
                'release_year': m.get('release_date', 'Unknown')[:4]
            })
    return results

def recommend_music_by_artists(track_ids):
    """
    For each liked track, get the first artist's ID and fetch top tracks of that artist.
    Combine and remove duplicates.
    """
    if not track_ids:
        return []
    artist_ids = set()
    for t_id in track_ids:
        track_info = fetch_spotify_track(t_id)
        if track_info and track_info.get('artists'):
            primary_artist_id = track_info['artists'][0]['id']
            artist_ids.add(primary_artist_id)

    recommended = []
    for a_id in artist_ids:
        try:
            top_tracks = spotify.artist_top_tracks(a_id, country='US')
            for t in top_tracks.get('tracks', []):
                recommended.append({
                    'id': t['id'],
                    'title': t['name'],
                    'artist': ', '.join(ar['name'] for ar in t['artists']),
                    'album': t['album']['name'],
                    'thumbnail': t['album']['images'][1]['url'] if len(t['album']['images']) > 1 else '',
                    'track_url': t['external_urls']['spotify']
                })
        except Exception as e:
            print(f"Error fetching top tracks for artist {a_id}: {e}")

    # Deduplicate by track ID
    unique = {}
    for r in recommended:
        unique[r['id']] = r
    final_list = list(unique.values())[:10]
    return final_list

def generate_ai_recommendations(username):
    """Simple AI approach: top genres for movies + top tracks by liked artists."""
    if not username:
        return {'Movies': [], 'Music': []}

    liked_dict = get_user_liked_items(username)
    liked_movie_ids = liked_dict['Movies']
    all_genres = []
    for mid in liked_movie_ids:
        md = fetch_movie_details(mid)
        if md and md.get('genres'):
            for g in md['genres']:
                all_genres.append(g['id'])
    top_genres = [g for g, _ in Counter(all_genres).most_common(3)]
    recommended_movies = recommend_movies_by_genre_ids(top_genres)
    recommended_movies = filter_out_disliked(recommended_movies, 'Movies', username)

    liked_music_ids = liked_dict['Music']
    recommended_tracks = recommend_music_by_artists(liked_music_ids)
    recommended_tracks = filter_out_disliked(recommended_tracks, 'Music', username)

    return {
        'Movies': recommended_movies,
        'Music': recommended_tracks
    }

# -------------------------
#        ROUTES
# -------------------------
@app.route('/')
def index():
    """Homepage: Show search form, liked items, and AI recs."""
    username = session.get('username')
    liked_dict = get_user_liked_items(username) if username else None

    liked_movies, liked_music, liked_videos, liked_images = [], [], [], []

    if liked_dict:
        # Fetch actual data for each liked item
        for mid in liked_dict['Movies']:
            mdata = fetch_movie_details(mid)
            if mdata and mdata.get('id'):
                liked_movies.append({
                    'id': mdata['id'],
                    'title': mdata['title'],
                    'description': mdata.get('overview', 'No description'),
                    'image_url': f"https://image.tmdb.org/t/p/w500{mdata['poster_path']}" if mdata.get('poster_path') else '',
                    'release_year': mdata.get('release_date', '')[:4] if mdata.get('release_date') else ''
                })

        for tid in liked_dict['Music']:
            tdata = fetch_spotify_track(tid)
            if tdata:
                liked_music.append({
                    'id': tdata['id'],
                    'title': tdata['name'],
                    'artist': ', '.join(a['name'] for a in tdata['artists']),
                    'album': tdata['album']['name'],
                    'thumbnail': tdata['album']['images'][1]['url'] if len(tdata['album']['images']) > 1 else '',
                    'track_url': tdata['external_urls']['spotify']
                })

        for vid in liked_dict['Videos']:
            try:
                detail_req = youtube.videos().list(part="snippet", id=vid)
                detail_resp = detail_req.execute()
                if detail_resp.get('items'):
                    snippet = detail_resp['items'][0]['snippet']
                    liked_videos.append({
                        'id': vid,
                        'title': snippet['title'],
                        'description': snippet.get('description', 'No description'),
                        'video_url': f"https://www.youtube.com/watch?v={vid}",
                        'thumbnail': snippet['thumbnails']['medium']['url']
                    })
            except Exception as e:
                print(f"Error fetching YouTube video info: {e}")

        for img_id in liked_dict['Images']:
            img_url = f"https://api.unsplash.com/photos/{img_id}"
            img_data = fetch_data(img_url, params={"client_id": UNSPLASH_ACCESS_KEY})
            if img_data.get('id'):
                liked_images.append({
                    'id': img_data['id'],
                    'title': img_data.get('description') or 'No title',
                    'description': img_data.get('alt_description', 'No desc'),
                    'image_url': img_data['urls']['regular']
                })

    # Generate AI recs
    ai_recs = generate_ai_recommendations(username) if username else {'Movies': [], 'Music': []}

    return render_template(
        'index.html',
        liked_movies=liked_movies,
        liked_music=liked_music,
        liked_videos=liked_videos,
        liked_images=liked_images,
        ai_movie_recs=ai_recs['Movies'],
        ai_music_recs=ai_recs['Music']
    )

@app.route('/register', methods=['GET','POST'])
def register():
    """Register a new user."""
    if request.method == 'POST':
        uname = request.form['username']
        passwd = request.form['password']
        hashed_pw = bcrypt.generate_password_hash(passwd).decode('utf-8')

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (uname,)).fetchone()
        if user:
            conn.close()
            # Instead of JSON, show an error on the register page
            return render_template('register.html', error="Username already exists. Please choose another.")
        
        conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (uname, hashed_pw))
        conn.commit()
        conn.close()
        return redirect('/login')
    return render_template('register.html', error=None)

@app.route('/login', methods=['GET','POST'])
def login():
    """User login."""
    if request.method == 'POST':
        uname = request.form.get('username')
        passwd = request.form.get('password')

        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (uname,)).fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], passwd):
            session['username'] = uname
            return redirect('/')
        else:
            # Instead of JSON, show an error on the login page
            return render_template('login.html', error="Invalid username or password.")
    return render_template('login.html', error=None)

@app.route('/logout')
def logout():
    """Log out the current user."""
    session.pop('username', None)
    return redirect('/')

@app.route('/recommend', methods=['POST'])
def recommend():
    """Handle search form submissions."""
    query = request.form.get('query')
    ctype = request.form.get('content_type')
    s_mode = request.form.get('search_mode', 'standard')
    year = request.form.get('year')

    if ctype == 'Movies':
        results = recommend_movies(query,
                                   person_search=(s_mode == 'person'),
                                   genre_search=(s_mode == 'genre'),
                                   year=year)
        results = filter_out_disliked(results, 'Movies', session.get('username'))
    elif ctype == 'Music':
        results = recommend_music(query, year=year)
        results = filter_out_disliked(results, 'Music', session.get('username'))
    elif ctype == 'Videos':
        results = recommend_videos(query, year=year)
        results = filter_out_disliked(results, 'Videos', session.get('username'))
    elif ctype == 'Images':
        results = recommend_images(query)
        results = filter_out_disliked(results, 'Images', session.get('username'))
    else:
        results = []

    return render_template('results.html',
                           results=results,
                           query=query,
                           content_type=ctype,
                           search_mode=s_mode,
                           year=year)

@app.route('/like', methods=['POST'])
def like():
    """Like an item."""
    username = session.get('username')
    if not username:
        return jsonify({'message': 'You must be logged in.'}), 403

    item_id = request.json.get('item_id')
    ctype = request.json.get('content_type')

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'message': 'No such user.'}), 400

    user_id = user['id']
    # Remove old preference
    conn.execute(
        "DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?",
        (user_id, item_id, ctype)
    )
    # Insert new like
    conn.execute(
        "INSERT INTO preferences (user_id, item_id, content_type, preference) VALUES (?, ?, ?, ?)",
        (user_id, item_id, ctype, 'like')
    )
    conn.commit()
    conn.close()
    return jsonify({'message': 'Liked successfully!'})

@app.route('/dislike', methods=['POST'])
def dislike():
    """Dislike an item."""
    username = session.get('username')
    if not username:
        return jsonify({'message': 'You must be logged in.'}), 403

    item_id = request.json.get('item_id')
    ctype = request.json.get('content_type')

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'message': 'No such user.'}), 400

    user_id = user['id']
    # Remove old preference
    conn.execute(
        "DELETE FROM preferences WHERE user_id = ? AND item_id = ? AND content_type = ?",
        (user_id, item_id, ctype)
    )
    # Insert new dislike
    conn.execute(
        "INSERT INTO preferences (user_id, item_id, content_type, preference) VALUES (?, ?, ?, ?)",
        (user_id, item_id, ctype, 'dislike')
    )
    conn.commit()
    conn.close()
    return jsonify({'message': 'Disliked successfully!'})

if __name__ == "__main__":
    app.run(debug=True)

