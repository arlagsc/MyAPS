# MES Orders API routes
from flask import Blueprint, jsonify, request
import requests
import logging

mes_api_bp = Blueprint('mes_api', __name__, url_prefix='/api')
logger = logging.getLogger(__name__)

MES_URL = 'http://localhost:8080'

@mes_api_bp.route('/mes/orders', methods=['GET'])
def get_mes_orders():
    workshop = request.args.get('workshop', 'ALL')
    try:
        r = requests.get(f'{MES_URL}/api/mes/orders?workshop={workshop}', timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f'MES API error: {e}')
    return jsonify({'success': False, 'message': str(e)}), 500


@mes_api_bp.route('/mes/orders/<parent_order>', methods=['GET'])
def get_mes_order_detail(parent_order):
    try:
        r = requests.get(f'{MES_URL}/api/mes/orders/{parent_order}', timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f'MES API error: {e}')
    return jsonify({'success': False, 'message': str(e)}), 500
