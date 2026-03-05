

# 车间看板
@app.route('/dashboard/smt')
def dashboard_smt():
    return render_template('dashboard_smt.html')

@app.route('/dashboard/dip')
def dashboard_dip():
    return render_template('dashboard_dip.html')

@app.route('/dashboard/assembly')
def dashboard_assembly():
    return render_template('dashboard_assembly.html')
