"""Legacy Order & Payment Processing Flask Application.

Description: Legacy monolithic REST API service for order processing.
Hosting Target: Static GCE VM instance (n1-standard-4).
"""

from flask import Flask, jsonify, request
from config import Config
from db import get_db_connection, query_orders, insert_order
from models import OrderCreateRequest

app = Flask(__name__)
app.config.from_object(Config)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for GCE load balancer/monitoring."""
    return jsonify({"status": "healthy", "service": "legacy-order-service", "version": "1.2.0"}), 200


@app.route("/api/v1/orders", methods=["GET"])
def list_orders():
    """Fetch paginated list of customer orders."""
    conn = get_db_connection()
    limit = int(request.args.get("limit", 50))
    orders = query_orders(conn, limit=limit)
    return jsonify({"orders": orders, "count": len(orders)}), 200


@app.route("/api/v1/orders", methods=["POST"])
def create_order():
    """Create a new customer order."""
    data = request.get_json() or {}
    if "item_id" not in data or "amount" not in data:
        return jsonify({"error": "Missing required fields item_id or amount"}), 400

    order_req = OrderCreateRequest(
        customer_id=data.get("customer_id", "guest"),
        item_id=data["item_id"],
        amount=float(data["amount"]),
        currency=data.get("currency", "USD")
    )
    conn = get_db_connection()
    created_order = insert_order(conn, order_req)
    return jsonify({"status": "created", "order": created_order}), 201


@app.route("/api/v1/orders/<int:order_id>", methods=["GET"])
def get_order(order_id: int):
    """Retrieve details for a specific order."""
    conn = get_db_connection()
    orders = query_orders(conn, limit=1)
    if not orders:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"order": orders[0]}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
