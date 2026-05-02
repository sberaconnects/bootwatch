import os
import threading
from flask import Flask, request, jsonify, render_template, abort, send_file
from db import (close_db, fetch_one, fetch_all, execute,
                get_or_create_device, get_or_create_revision)


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev')
    app.teardown_appcontext(close_db)

    def _slow_mult():
        return float(os.environ.get('SLOW_BOOT_MULTIPLIER', 1.2))

    def _very_slow_mult():
        return float(os.environ.get('VERY_SLOW_BOOT_MULTIPLIER', 2.0))

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

    # ---------- Pages ----------

    @app.route('/')
    def overview():
        device_count = (fetch_one('SELECT COUNT(*) AS n FROM bw_devices') or {}).get('n', 0)
        boot_count   = (fetch_one('SELECT COUNT(*) AS n FROM bw_boots') or {}).get('n', 0)
        vm = _very_slow_mult()
        today_slow = (fetch_one(
            'SELECT COUNT(*) AS n FROM bw_boots b '
            'JOIN (SELECT device_id, AVG(boot_time_s) AS avg_t FROM bw_boots GROUP BY device_id) a '
            '  ON b.device_id = a.device_id '
            'WHERE DATE(b.collected_at) = CURDATE() AND b.boot_time_s > a.avg_t * %s',
            (vm,)
        ) or {}).get('n', 0)
        fleet_avg = (fetch_one('SELECT AVG(boot_time_s) AS a FROM bw_boots') or {}).get('a')

        devices = fetch_all('''
            SELECT d.id, d.name, d.label,
                   b.boot_time_s AS last_boot,
                   b.collected_at AS last_seen,
                   r.revision AS last_revision
            FROM bw_devices d
            LEFT JOIN bw_boots b ON b.id = (
                SELECT id FROM bw_boots WHERE device_id = d.id ORDER BY collected_at DESC LIMIT 1
            )
            LEFT JOIN bw_sw_revisions r ON r.id = b.revision_id
            ORDER BY d.name
        ''')
        for dev in devices:
            dev['sparkline'] = fetch_all(
                'SELECT boot_time_s FROM bw_boots WHERE device_id = %s ORDER BY collected_at DESC LIMIT 5',
                (dev['id'],)
            )
            dev['avg_boot'] = (fetch_one(
                'SELECT AVG(boot_time_s) AS a FROM bw_boots WHERE device_id = %s', (dev['id'],)
            ) or {}).get('a')

        recent = fetch_all('''
            SELECT b.id, d.name AS device_name, b.boot_time_s, r.revision, b.collected_at
            FROM bw_boots b
            JOIN bw_devices d ON d.id = b.device_id
            JOIN bw_sw_revisions r ON r.id = b.revision_id
            ORDER BY b.collected_at DESC LIMIT 10
        ''')

        slow_services = fetch_all('''
            SELECT service, AVG(time_s) AS avg_time, COUNT(*) AS n_boots
            FROM bw_blame_entries GROUP BY service ORDER BY avg_time DESC LIMIT 10
        ''')
        max_svc_time = slow_services[0]['avg_time'] if slow_services else 1

        return render_template('overview.html',
            device_count=device_count, boot_count=boot_count,
            today_slow=today_slow, fleet_avg=fleet_avg,
            devices=devices, recent=recent,
            slow_services=slow_services, max_svc_time=max_svc_time,
            slow_mult=_slow_mult(), very_slow_mult=vm,
        )

    @app.route('/boots')
    def boots():
        page      = max(1, request.args.get('page', 1, type=int))
        per_page  = 50
        device_f  = request.args.get('device', '')
        rev_f     = request.args.get('revision', '')
        date_f    = request.args.get('date', '')
        svc_f     = request.args.get('service', '')

        where_clauses, args = [], []
        if device_f:
            where_clauses.append('d.name = %s'); args.append(device_f)
        if rev_f:
            where_clauses.append('r.revision = %s'); args.append(rev_f)
        if date_f:
            where_clauses.append('DATE(b.collected_at) = %s'); args.append(date_f)
        if svc_f:
            where_clauses.append(
                'b.id IN (SELECT boot_id FROM bw_blame_entries WHERE service=%s ORDER BY time_s DESC LIMIT 500)'
            ); args.append(svc_f)

        where = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

        total = (fetch_one(
            f'SELECT COUNT(*) AS n FROM bw_boots b '
            f'JOIN bw_devices d ON d.id=b.device_id '
            f'JOIN bw_sw_revisions r ON r.id=b.revision_id {where}', args
        ) or {}).get('n', 0)

        offset = (page - 1) * per_page
        boots_list = fetch_all(
            f'SELECT b.id, b.device_id, d.name AS device_name, b.boot_time_s, r.revision, '
            f'b.collected_at, b.source '
            f'FROM bw_boots b JOIN bw_devices d ON d.id=b.device_id '
            f'JOIN bw_sw_revisions r ON r.id=b.revision_id '
            f'{where} ORDER BY b.collected_at DESC LIMIT %s OFFSET %s',
            args + [per_page, offset]
        )
        avgs = {r['device_id']: r['avg_t'] for r in fetch_all(
            'SELECT device_id, AVG(boot_time_s) AS avg_t FROM bw_boots GROUP BY device_id'
        )}
        all_devices   = fetch_all('SELECT DISTINCT name FROM bw_devices ORDER BY name')
        all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision')

        return render_template('boots.html',
            boots=boots_list, total=total, page=page, per_page=per_page,
            device_f=device_f, rev_f=rev_f, date_f=date_f, svc_f=svc_f,
            all_devices=all_devices, all_revisions=all_revisions,
            avgs=avgs, slow_mult=_slow_mult(), very_slow_mult=_very_slow_mult(),
        )

    @app.route('/boot/<int:boot_id>')
    def boot_detail(boot_id):
        boot = fetch_one(
            'SELECT b.*, d.name AS device_name, d.id AS device_id, r.revision '
            'FROM bw_boots b JOIN bw_devices d ON d.id=b.device_id '
            'JOIN bw_sw_revisions r ON r.id=b.revision_id WHERE b.id=%s', (boot_id,)
        )
        if not boot:
            abort(404)
        blame = fetch_all(
            'SELECT service, time_s FROM bw_blame_entries WHERE boot_id=%s ORDER BY time_s DESC',
            (boot_id,)
        )
        max_blame = blame[0]['time_s'] if blame else 1
        trend = list(reversed(fetch_all(
            'SELECT id, boot_time_s, collected_at FROM bw_boots '
            'WHERE device_id=%s ORDER BY collected_at DESC LIMIT 10',
            (boot['device_id'],)
        )))
        trend_max = max((t['boot_time_s'] for t in trend), default=1)
        dev_avg = (fetch_one(
            'SELECT AVG(boot_time_s) AS a FROM bw_boots WHERE device_id=%s', (boot['device_id'],)
        ) or {}).get('a', boot['boot_time_s'])
        delta = boot['boot_time_s'] - dev_avg

        return render_template('boot_detail.html',
            boot=boot, blame=blame, max_blame=max_blame,
            trend=trend, trend_max=trend_max,
            dev_avg=dev_avg, delta=delta,
            slow_mult=_slow_mult(), very_slow_mult=_very_slow_mult(),
        )

    @app.route('/devices')
    def devices():
        rows = fetch_all('''
            SELECT d.id, d.name, d.label, d.ip_addr, d.created_at,
                   COUNT(b.id) AS boot_count,
                   AVG(b.boot_time_s) AS avg_boot,
                   MIN(b.boot_time_s) AS min_boot,
                   MAX(b.boot_time_s) AS max_boot,
                   MAX(b.collected_at) AS last_seen
            FROM bw_devices d LEFT JOIN bw_boots b ON b.device_id = d.id
            GROUP BY d.id ORDER BY d.name
        ''')
        return render_template('devices.html', devices=rows)

    @app.route('/device/<int:device_id>')
    def device_detail(device_id):
        device = fetch_one('SELECT * FROM bw_devices WHERE id=%s', (device_id,))
        if not device:
            abort(404)
        boots_list = fetch_all(
            'SELECT b.id, b.boot_time_s, b.collected_at, b.source, r.revision '
            'FROM bw_boots b JOIN bw_sw_revisions r ON r.id=b.revision_id '
            'WHERE b.device_id=%s ORDER BY b.collected_at DESC LIMIT 50',
            (device_id,)
        )
        stats = fetch_one(
            'SELECT COUNT(*) AS n, AVG(boot_time_s) AS avg_t, '
            'MIN(boot_time_s) AS min_t, MAX(boot_time_s) AS max_t '
            'FROM bw_boots WHERE device_id=%s', (device_id,)
        ) or {}
        return render_template('device_detail.html',
            device=device, boots=boots_list, stats=stats,
            slow_mult=_slow_mult(), very_slow_mult=_very_slow_mult(),
        )

    @app.route('/firmware')
    def firmware():
        revisions = fetch_all('''
            SELECT r.id, r.revision,
                   COUNT(DISTINCT b.device_id) AS device_count,
                   COUNT(b.id) AS boot_count,
                   AVG(b.boot_time_s) AS avg_boot,
                   MIN(b.boot_time_s) AS min_boot,
                   MAX(b.boot_time_s) AS max_boot
            FROM bw_sw_revisions r LEFT JOIN bw_boots b ON b.revision_id = r.id
            GROUP BY r.id ORDER BY r.revision DESC
        ''')
        return render_template('firmware.html', revisions=revisions)

    @app.route('/services')
    def services():
        rev_f = request.args.get('revision', '')
        where = 'JOIN bw_sw_revisions r ON r.id=bt.revision_id WHERE r.revision=%s' if rev_f else ''
        args  = [rev_f] if rev_f else []
        rows = fetch_all(
            f'SELECT be.service, AVG(be.time_s) AS avg_time, MAX(be.time_s) AS max_time, '
            f'COUNT(*) AS n_boots '
            f'FROM bw_blame_entries be JOIN bw_boots bt ON bt.id=be.boot_id {where} '
            f'GROUP BY be.service ORDER BY avg_time DESC LIMIT 50',
            args
        )
        # worst device per service
        for svc in rows:
            wd = fetch_one(
                'SELECT d.name FROM bw_blame_entries be '
                'JOIN bw_boots bt ON bt.id=be.boot_id JOIN bw_devices d ON d.id=bt.device_id '
                'WHERE be.service=%s ORDER BY be.time_s DESC LIMIT 1',
                (svc['service'],)
            )
            svc['worst_device'] = wd['name'] if wd else '—'

        all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision DESC')
        max_time = rows[0]['avg_time'] if rows else 1
        return render_template('services.html',
            services=rows, max_time=max_time,
            all_revisions=all_revisions, rev_f=rev_f,
        )

    @app.route('/perf')
    def perf():
        device_f = request.args.get('device', '')
        rev_f    = request.args.get('revision', '')

        wp, wa = [], []
        if device_f:
            wp.append('d.name = %s'); wa.append(device_f)
        if rev_f:
            wp.append('r.revision = %s'); wa.append(rev_f)
        where = ('WHERE ' + ' AND '.join(wp)) if wp else ''

        stats = fetch_all(
            f'SELECT ps.*, d.name AS device_name, r.revision '
            f'FROM bw_perf_stats ps '
            f'JOIN bw_devices d ON d.id=ps.device_id '
            f'JOIN bw_sw_revisions r ON r.id=ps.revision_id '
            f'{where} ORDER BY ps.collected_at DESC LIMIT 20', wa
        )

        fg_where = 'WHERE d.name=%s' if device_f else ''
        fg_args  = [device_f] if device_f else []
        flamegraph = fetch_one(
            f'SELECT fg.*, d.name AS device_name, r.revision '
            f'FROM bw_flamegraphs fg '
            f'JOIN bw_devices d ON d.id=fg.device_id '
            f'JOIN bw_sw_revisions r ON r.id=fg.revision_id '
            f'{fg_where} ORDER BY fg.generated_at DESC LIMIT 1', fg_args
        )

        ipc_trend = fetch_all(
            'SELECT ps.ipc, ps.collected_at, r.revision '
            'FROM bw_perf_stats ps JOIN bw_sw_revisions r ON r.id=ps.revision_id '
            + ('JOIN bw_devices d ON d.id=ps.device_id WHERE d.name=%s ' if device_f else '')
            + 'ORDER BY ps.collected_at ASC LIMIT 20',
            [device_f] if device_f else []
        )

        all_devices   = fetch_all('SELECT DISTINCT name FROM bw_devices ORDER BY name')
        all_revisions = fetch_all('SELECT revision FROM bw_sw_revisions ORDER BY revision DESC')
        selected_device = fetch_one('SELECT id FROM bw_devices WHERE name=%s', (device_f,)) if device_f else None

        return render_template('perf.html',
            stats=stats, flamegraph=flamegraph, ipc_trend=ipc_trend,
            all_devices=all_devices, all_revisions=all_revisions,
            device_f=device_f, rev_f=rev_f,
            selected_device=selected_device,
        )

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
