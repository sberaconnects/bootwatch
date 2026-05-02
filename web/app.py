import os
import threading
from flask import Flask, request, jsonify, render_template, abort, send_file
from db import (close_db, fetch_one, fetch_all, execute,
                get_or_create_device, get_or_create_revision)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev')
    app.teardown_appcontext(close_db)

    # ---------- API ----------

    @app.route('/api/boot', methods=['POST'])
    def api_boot():
        data = request.get_json(silent=True) or {}
        required = ['device_ip', 'device_name', 'revision', 'boot_time_s', 'blame']
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify(error=f"missing fields: {missing}"), 400

        device_id   = get_or_create_device(data['device_ip'], data['device_name'], data.get('device_label', ''))
        revision_id = get_or_create_revision(data['revision'])

        boot_id = execute(
            'INSERT INTO bw_boots (device_id, revision_id, boot_time_s, source, raw_blame, raw_chain) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (device_id, revision_id, data['boot_time_s'],
             data.get('source', 'ssh_pull'),
             data.get('raw_blame', ''),
             data.get('critical_chain', ''))
        )

        for entry in data.get('blame', []):
            execute(
                'INSERT INTO bw_blame_entries (boot_id, service, time_s) VALUES (%s, %s, %s)',
                (boot_id, entry['service'], entry['time_s'])
            )

        ps = data.get('perf_stat')
        if ps:
            execute(
                'INSERT INTO bw_perf_stats '
                '(device_id, revision_id, duration_s, cycles, instructions, ipc, '
                ' cache_misses, cache_refs, cache_miss_pct, '
                ' branch_misses, branch_total, branch_miss_pct, raw_output) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (device_id, revision_id,
                 ps.get('duration_s', 10),
                 ps.get('cycles'), ps.get('instructions'), ps.get('ipc'),
                 ps.get('cache_misses'), ps.get('cache_refs'), ps.get('cache_miss_pct'),
                 ps.get('branch_misses'), ps.get('branch_total'), ps.get('branch_miss_pct'),
                 ps.get('raw_output', ''))
            )

        return jsonify(boot_id=boot_id), 201

    @app.route('/api/perf/stat', methods=['POST'])
    def api_perf_stat():
        data = request.get_json(silent=True) or {}
        missing = [f for f in ['device_ip', 'revision'] if f not in data]
        if missing:
            return jsonify(error=f'missing: {missing}'), 400
        device_id   = get_or_create_device(data['device_ip'], data.get('device_name', 'device'), '')
        revision_id = get_or_create_revision(data['revision'])
        ps = data.get('perf_stat', data)
        execute(
            'INSERT INTO bw_perf_stats '
            '(device_id, revision_id, duration_s, cycles, instructions, ipc, '
            ' cache_misses, cache_refs, cache_miss_pct, branch_misses, branch_total, branch_miss_pct, raw_output) '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (device_id, revision_id,
             ps.get('duration_s', 10), ps.get('cycles'), ps.get('instructions'), ps.get('ipc'),
             ps.get('cache_misses'), ps.get('cache_refs'), ps.get('cache_miss_pct'),
             ps.get('branch_misses'), ps.get('branch_total'), ps.get('branch_miss_pct'),
             ps.get('raw_output', ''))
        )
        return jsonify(ok=True), 201

    @app.route('/api/flamegraph/<int:device_id>', methods=['POST'])
    def api_flamegraph_trigger(device_id):
        device = fetch_one('SELECT * FROM bw_devices WHERE id = %s', (device_id,))
        if not device:
            return jsonify(error='device not found'), 404
        body = request.get_json(silent=True) or {}
        revision_str = body.get('revision', 'unknown')
        revision_id = get_or_create_revision(revision_str)
        fg_id = execute(
            'INSERT INTO bw_flamegraphs (device_id, revision_id, status) VALUES (%s, %s, %s)',
            (device_id, revision_id, 'pending')
        )
        _app = app
        from collector import start_flamegraph_job
        threading.Thread(
            target=start_flamegraph_job,
            args=(fg_id, device, revision_str, _app),
            daemon=True
        ).start()
        return jsonify(flamegraph_id=fg_id), 202

    @app.route('/api/flamegraph/<int:device_id>/status')
    def api_flamegraph_status(device_id):
        fg = fetch_one(
            'SELECT id, status, svg_path, generated_at FROM bw_flamegraphs '
            'WHERE device_id = %s ORDER BY generated_at DESC LIMIT 1',
            (device_id,)
        )
        if not fg:
            return jsonify(status='none'), 200
        return jsonify(
            flamegraph_id=fg['id'],
            status=fg['status'],
            svg_path=fg['svg_path'],
            generated_at=str(fg['generated_at']) if fg['generated_at'] else None
        )

    # ---------- Page stubs (filled in Tasks 8-14) ----------

    @app.route('/')
    def overview():
        return render_template('overview.html')

    @app.route('/boots')
    def boots():
        return render_template('boots.html', boots=[], total=0, page=1, per_page=50)

    @app.route('/boot/<int:boot_id>')
    def boot_detail(boot_id):
        boot = fetch_one('SELECT * FROM bw_boots WHERE id = %s', (boot_id,))
        if not boot:
            abort(404)
        return render_template('boot_detail.html', boot=boot, blame=[], trend=[])

    @app.route('/devices')
    def devices():
        return render_template('devices.html', devices=[])

    @app.route('/device/<int:device_id>')
    def device_detail(device_id):
        device = fetch_one('SELECT * FROM bw_devices WHERE id = %s', (device_id,))
        if not device:
            abort(404)
        return render_template('device_detail.html', device=device, boots=[])

    @app.route('/firmware')
    def firmware():
        return render_template('firmware.html', revisions=[])

    @app.route('/services')
    def services():
        return render_template('services.html', services=[])

    @app.route('/perf')
    def perf():
        return render_template('perf.html', stats=[], flamegraph=None)

    @app.route('/flamegraph/<int:fg_id>/svg')
    def serve_flamegraph_svg(fg_id):
        fg = fetch_one('SELECT svg_path FROM bw_flamegraphs WHERE id=%s AND status=%s', (fg_id, 'done'))
        if not fg or not fg['svg_path'] or not os.path.exists(fg['svg_path']):
            abort(404)
        return send_file(fg['svg_path'], mimetype='image/svg+xml')

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', debug=True)
