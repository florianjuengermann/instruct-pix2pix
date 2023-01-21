import flask
from tempfile import NamedTemporaryFile

import edit_cli

app = flask.Flask(__name__)

# route /spell accepts and image and a text description of the spell


@app.route('/spell', methods=['POST'])
def spell():
    image = flask.request.files['image']
    spell = flask.request.form['spell']
    steps = int(flask.request.form.get("steps", 100))
    cfg_text = float(flask.request.form.get("cfg_text", 7.5))
    cfg_image = float(flask.request.form.get("cfg_image", 1.5))

    args = {
        "edit": spell,
        "steps": steps,
        "cfg_text": cfg_text,
        "cfg_image": cfg_image,
    }

    try:
        with NamedTemporaryFile(suffix='.jpg') as img_in, NamedTemporaryFile(suffix='.jpg') as img_out:
            image.save(img_in.name)
            args['input'] = img_in.name
            args['output'] = img_out.name
            edit_cli.run(args)
            return flask.send_file(img_out.name)
    except Exception as e:
        return flask.jsonify({'success': False, 'error': str(e)})

    # return flask.jsonify({'success': True})
