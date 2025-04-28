# streamlit_spotify_outfit.py
import json
import os
import base64
import requests
import streamlit as st

# -------- LangChain Imports --------
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnablePassthrough
from langchain_core.runnables import RunnableMap
from langchain.globals import set_debug

# -------- Custom Prompt --------
from prompt import vision_prompt

# -------- Load Environment Variables from Streamlit Secrets --------
set_debug(True)

# Set OpenAI API Key from secrets
os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

# -------- Step 1: Vision Model Setup --------
class ImageInformation(BaseModel):
    """Information about an image."""
    image_description: str = Field(description="A short description of the image")
    people_count: int = Field(description="Number of humans in the picture")
    main_objects: list[str] = Field(description="List of the main objects in the picture")
    main_character: str = Field(description="the main Character in the picture")
    outfit_characteristics: list[str] = Field(description="Characteristic of Outfit wore by main character")
    background_aesthetics: list[str] = Field(description="A list of characteristics of background of the main character")
    music_genre: list[str] = Field(description="A list of musical genre the photo belongs")

parser = JsonOutputParser(pydantic_object=ImageInformation)

def load_image(inputs: dict) -> dict:
    """Load image from file and encode it as base64."""
    image_path = inputs["image_path"]
    with open(image_path, "rb") as image_file:
        image_base64 = base64.b64encode(image_file.read()).decode('utf-8')
    return {"image": image_base64, "prompt": inputs["prompt"]}

load_image_chain = RunnableLambda(load_image)

def image_model(inputs: dict) -> dict:
    """Invoke GPT-4 Vision with image and prompt and parse output safely."""
    model = ChatOpenAI(model="o4-mini-2025-04-16", max_tokens=512)
    message = model.invoke([
        HumanMessage(content=[
            {"type": "text", "text": inputs["prompt"]},
            {"type": "text", "text": parser.get_format_instructions()},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{inputs['image']}"}}
        ])
    ])
    text_output = message.content.strip()

    if not text_output:
        raise ValueError("Model returned empty output. Likely token limit exceeded or bad input.")

    # Try parsing as JSON manually
    try:
        data = json.loads(text_output)
    except Exception:
        import re
        matches = re.findall(r'\{[\s\S]*\}', text_output)
        if matches:
            data = json.loads(matches[0])
        else:
            raise ValueError(f"Model output is not valid JSON:\n{text_output}")

    return data

image_model_chain = RunnableLambda(image_model)

vision_chain = load_image_chain | image_model_chain

def get_image_informations(image_path: str) -> dict:
    return vision_chain.invoke({
        "image_path": image_path,
        "prompt": vision_prompt
    })

# -------- Step 2: Spotify and Search Setup --------
SPOTIFY_CLIENT_ID = st.secrets["SPOTIFY_CLIENT_ID"]
SPOTIFY_CLIENT_SECRET = st.secrets["SPOTIFY_CLIENT_SECRET"]

# Hardcoded artist list
ARTISTS = ["Kanye West", "Frank Ocean", "ASAP Rocky", "Kendrick Lamar", "J. Cole", "Drake"]

# Genre Mapping
GENRE_MAPPING = {
    "hip-hop": "hip-hop",
    "trap": "trap",
    "r&b": "r-n-b",
    "pop": "pop",
    "soul": "soul",
    "edm": "edm",
    "rock": "rock",
    "indie rock": "indie",
    "synthwave": "synthwave",
    "electronic": "electronic"
}

def get_spotify_access_token():
    auth_string = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    b64_auth = base64.b64encode(auth_string.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials"
    }
    token_url = "https://accounts.spotify.com/api/token"
    response = requests.post(token_url, headers=headers, data=data)
    access_token = response.json().get("access_token")
    return access_token

def search_spotify(access_token, artists, genres):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    all_tracks = []

    for artist in artists:
        for genre in genres:
            query = f'artist:"{artist}" genre:"{genre}" year:2010-2025'
            params = {
                "q": query,
                "type": "track",
                "limit": 5,
                "market": "US"
            }
            response = requests.get("https://api.spotify.com/v1/search", headers=headers, params=params)

            if response.status_code != 200:
                continue

            tracks = response.json().get("tracks", {}).get("items", [])
            for track in tracks:
                all_tracks.append({
                    "name": track["name"],
                    "artist": track["artists"][0]["name"],
                    "url": track["external_urls"]["spotify"],
                    "popularity": track.get("popularity", 0)
                })

    all_tracks = sorted(all_tracks, key=lambda x: x['popularity'], reverse=True)

    seen = set()
    unique_tracks = []
    for t in all_tracks:
        key = (t['name'], t['artist'])
        if key not in seen:
            unique_tracks.append(t)
            seen.add(key)

    return unique_tracks[:20]

# -------- Step 3: Streamlit App UI --------
st.set_page_config(page_title="Outfit to Spotify Songs", page_icon="🎵")
st.title("🎵 Outfit ➔ Spotify Songs")
st.markdown("Upload an outfit image, and we'll suggest music vibes based on your look!")

uploaded_file = st.file_uploader("Upload your outfit image", type=["jpg", "jpeg", "png"])

if uploaded_file:
    temp_path = os.path.join("temp_uploaded_image.jpg")
    with open(temp_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    st.image(uploaded_file, caption="Uploaded Image", use_column_width=True)

    with st.spinner("Analyzing outfit..."):
        result = get_image_informations(temp_path)

    st.success("Analysis complete!")

    st.subheader("🔍 Outfit Analysis:")
    st.json(result)

    predicted_genres = result.get('music_genre', [])

    mapped_genres = []
    for genre in predicted_genres:
        key = genre.lower()
        if key in GENRE_MAPPING:
            mapped_genres.append(GENRE_MAPPING[key])

    if not mapped_genres:
        st.warning("No matching genres found! Defaulting to hip-hop.")
        mapped_genres = ["hip-hop"]

    access_token = get_spotify_access_token()
    if not access_token:
        st.error("Spotify Authentication Failed!")
    else:
        with st.spinner("Fetching songs matching your vibe..."):
            songs = search_spotify(access_token, ARTISTS, mapped_genres)

        if songs:
            st.subheader("🎶 Songs Inspired by Your Outfit:")
            for song in songs:
                st.markdown(f"- [{song['name']} - {song['artist']}]({song['url']})")
        else:
            st.warning("No songs found matching the outfit style.")
