from flask import Flask, request, send_file, jsonify
from tempfile import NamedTemporaryFile

import edit_cli


model_args = {

}

app = Flask(__name__)


instructp2p = edit_cli.InstructP2P(model_args)
# route /spell accepts and image and a text description of the spell


@app.route('/spell', methods=['POST'])
def spell():
    image = request.files['image']
    spell = request.form['spell']
    steps = int(request.form.get("steps", 50))
    cfg_text = float(request.form.get("cfg_text", 7.5))
    cfg_image = float(request.form.get("cfg_image", 1.5))

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
            instructp2p.run(args)
            return send_file(img_out.name)
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'error': str(e)})

    # return flask.jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=False)
