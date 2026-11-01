from flask import Blueprint, render_template, request, jsonify
from app.core.security import login_required
from app.core.distributed_query import DistributedQueryProcessor
from app.config import BRANCHES

query_bp = Blueprint("query", __name__, url_prefix="/query-console")

@query_bp.route("/", methods=["GET", "POST"])
@login_required
def query_console():
    query_type = request.form.get("query_type", "AGGREGATION")
    min_balance = float(request.form.get("min_balance", 10000.0))
    account_type = request.form.get("account_type") or None
    keyword = request.form.get("keyword") or None

    result = None

    if request.method == "POST":
        if query_type == "AGGREGATION":
            result = DistributedQueryProcessor.execute_distributed_aggregation()
        elif query_type == "HIGH_VALUE":
            result = DistributedQueryProcessor.execute_global_account_search(min_balance=min_balance, account_type=account_type)
        elif query_type == "AUDIT":
            result = DistributedQueryProcessor.execute_global_transaction_audit(keyword=keyword)
    else:
        # Default run aggregation for immediate display
        result = DistributedQueryProcessor.execute_distributed_aggregation()

    return render_template(
        "query_console.html",
        result=result,
        selected_type=query_type,
        min_balance=min_balance,
        branches=BRANCHES
    )

@query_bp.route("/api/run", methods=["POST"])
@login_required
def api_run_query():
    data = request.get_json() or {}
    q_type = data.get("query_type", "AGGREGATION")
    if q_type == "AGGREGATION":
        res = DistributedQueryProcessor.execute_distributed_aggregation()
    elif q_type == "SEARCH":
        res = DistributedQueryProcessor.execute_global_account_search(
            min_balance=float(data.get("min_balance", 0.0)),
            account_type=data.get("account_type")
        )
    elif q_type == "AUDIT":
        res = DistributedQueryProcessor.execute_global_transaction_audit(keyword=data.get("keyword"))
    else:
        res = {"error": "Unknown query type"}
    return jsonify(res)
