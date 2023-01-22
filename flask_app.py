from flask import Flask, request, send_file, jsonify
from tempfile import NamedTemporaryFile
from dotenv import load_dotenv
from supabase import create_client, Client, SupabaseStorageClient
from PIL import Image, ImageOps
from flask_cors import CORS

import os
import io
import requests
import uuid

import edit_cli

load_dotenv()

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


if __name__ == '__main__':
    app.run(debug=False)
