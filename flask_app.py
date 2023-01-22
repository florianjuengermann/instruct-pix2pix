import edit_cli
from flask import Flask, request, send_file, jsonify
from tempfile import NamedTemporaryFile
from dotenv import load_dotenv
from supabase import create_client, Client, SupabaseStorageClient
from PIL import Image, ImageOps
from flask_cors import CORS
from datetime import datetime

import os
import io
import requests
import uuid
import time
import random
import replicate
import openai


load_dotenv()

openai.organization = "org-1WwEWlbIVVO1mbZlQEWBZsXe"
openai.api_key = os.getenv("OPENAI_API_KEY")
openai.Model.list()


model_args = {

}

app = Flask(__name__)
CORS(app)

instructp2p = edit_cli.InstructP2P(model_args)
# route /spell accepts and image and a text description of the spell


url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)
supabase_storage: SupabaseStorageClient = supabase.storage()


def run_spell(image, spell, steps, cfg_text, cfg_image, out_img_name):
    args = {
        "edit": spell,
        "steps": steps,
        "cfg_text": cfg_text,
        "cfg_image": cfg_image,
    }
    with NamedTemporaryFile(suffix='.jpg') as img_in:
        image.save(img_in.name)
        args['input'] = img_in.name
        args['output'] = out_img_name
        instructp2p.run(args)


@app.route('/spell-img', methods=['POST'])
def spell_img():
    image = request.files['image']
    spell = request.form['spell']
    steps = int(request.form.get("steps", 50))
    cfg_text = float(request.form.get("cfg_text", 7.5))
    cfg_image = float(request.form.get("cfg_image", 1.5))

    try:
        with NamedTemporaryFile(suffix='.jpg') as img_out:
            run_spell(image, spell, steps, cfg_text, cfg_image, img_out.name)
            return send_file(img_out.name)
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'error': str(e)})

    # return flask.jsonify({'success': True})


def download_resize_image(img_url):
    image = Image.open(io.BytesIO(
        requests.get(img_url, stream=True).content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    # resize image to max 768px on longest side
    if max(image.width, image.height) > 768:
        if image.width > image.height:
            image = image.resize(
                (768, int(768 * image.height / image.width)))
        else:
            image = image.resize(
                (int(768 * image.width / image.height), 768))
    return image


@app.route('/spell', methods=['POST'])
def spell():
    data = request.get_json()
    img_url = data['image_url']
    spell = data['spell']
    steps = int(data.get("steps", 50))
    cfg_text = float(data.get("cfg_text", 7.5))
    cfg_image = float(data.get("cfg_image", 1.5))

    try:
        # download image
        print(f"img_url: {img_url}")
        image = download_resize_image(img_url)

        with NamedTemporaryFile(suffix='.jpg') as img_out:
            run_spell(image, spell, steps, cfg_text, cfg_image, img_out.name)
            # upload image to supabase
            img_uuid = str(uuid.uuid4())
            res = supabase_storage.from_("images").upload(
                f"{img_uuid}.jpg", img_out.name)
            resJson = res.json()
            key = resJson['Key']
            url = f"{os.environ.get('SUPABASE_URL')}/storage/v1/object/public/{key}"
            return jsonify({'success': True, 'url': url})
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'error': str(e)})


def clip_interrogator(image):
    model = replicate.models.get("pharmapsychotic/clip-interrogator")
    version = model.versions.get(
        "a4a8bafd6089e1716b06057c42b19378250d008b80fe87caa5cd36d40c1eda90")

    # https://replicate.com/pharmapsychotic/clip-interrogator/versions/a4a8bafd6089e1716b06057c42b19378250d008b80fe87caa5cd36d40c1eda90#input
    with NamedTemporaryFile(suffix='.jpg') as img_in:
        image.save(img_in.name)
        inputs = {
            # Input image
            'image': open(img_in.name, "rb"),

            # Choose ViT-L for Stable Diffusion 1, and ViT-H for Stable Diffusion
            # 2
            'clip_model_name': "ViT-L-14/openai",

            # Prompt mode (best takes 10-20 seconds, fast takes 1-2 seconds).
            # 'mode': "best",
            'mode': "fast",
        }

        # https://replicate.com/pharmapsychotic/clip-interrogator/versions/a4a8bafd6089e1716b06057c42b19378250d008b80fe87caa5cd36d40c1eda90#output-schema
        output = version.predict(**inputs)
        print("clip output: ", output)
        return output


def get_gpt_edit(desc):
    prompt = f"""
You can edit pictures by writing a prompt. You are the funniest person on earth.

DESCRIPTION:
a watercolor painting of a sea turtle, a digital painting, by Kubisi art, featured on dribbble, medibang, warm saturated palette, red and green tones, turquoise horizon, digital art h 9 6 0, detailed scenery —width 672, illustration:.4, spray art, artstatiom

EDIT:
Make the sea turtle into a clown

DESCRIPTION:
{desc}

EDIT:
"""
    r = openai.Completion.create(
        model="text-davinci-003",
        prompt=prompt,
        max_tokens=20,
        temperature=1
    )
    text = r["choices"][0]["text"]
    print("gpt output: ", text)
    return text


@app.route('/gpt-post', methods=['POST'])
def gpt_post():
    data = request.get_json()
    post_id = data['id']
    img_url = data['image_url']

    image = download_resize_image(img_url)

    desc = clip_interrogator(image)
    spell = get_gpt_edit(desc)

    # cast spell and add it to supabase
    steps = 50
    cfg_text = 10.5
    cfg_image = 1.5

    with NamedTemporaryFile(suffix='.jpg') as img_out:
        run_spell(image, spell, steps, cfg_text, cfg_image, img_out.name)
        img_uuid = str(uuid.uuid4())
        res = supabase_storage.from_("images").upload(
            f"{img_uuid}.jpg", img_out.name)
        resJson = res.json()
        key = resJson['Key']
        url = f"{os.environ.get('SUPABASE_URL')}/storage/v1/object/public/{key}"

        # update database
        """
        const id = Date.now() + Math.floor(Math.random() * 100);
        await supabase.from("posts").insert({
            id: id,
            image: json.url,
            spell: spellName,
            created_at: new Date().toISOString(),
            parent: post.id,
        });
        """
        new_id = int(time.time() * 1000) + random.randint(0, 100)
        supabase.from_("posts").insert({
            "id": new_id,
            "username": "ChatGPT",
            "userid": "chatgpt",
            "userPicture": "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcRB0gYfYYURpZqDZuD5NuWgIGJbGZ3knkGDpKonU1VP&s",
            "image": url,
            "spell": spell,
            "created_at": datetime.now().isoformat(),
            "parent": post_id,
        }).execute()
    return jsonify({'success': True, 'url': url})


if __name__ == '__main__':
    app.run(debug=False)
