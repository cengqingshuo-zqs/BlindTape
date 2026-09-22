"""命令行入口。

用法示例：
    python -m data_layer.cli run-all                  # 全流程：拉列表 -> 增量拉历史 -> 出标的池清单
    python -m data_layer.cli fetch-list
    python -m data_layer.cli fetch-hist                # 增量更新所有标的
    python -m data_layer.cli fetch-hist --full         # 全量重新拉取所有标的
    python -m data_layer.cli fetch-hist --symbols 510300 159915
    python -m data_layer.cli fetch-hist --limit 20     # 只拉前20只，调试用
    python -m data_layer.cli build-pool
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timedelta

from . import db, fetch
from .config import Config, load_config

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def cmd_fetch_list(conn: sqlite3.Connection, cfg: Config) -> None:
    df = fetch.with_retry(
        fetch.fetch_etf_list,
        max_retries=cfg.request.max_retries,
        backoff_sec=cfg.request.retry_backoff_sec,
    )
    rows = df.to_dict(orient="records")
    db.upsert_etf_list(conn, rows, snapshot_at=_now_iso())
    conn.commit()
    logger.info("fetch-list: 拉取到 %d 只ETF", len(rows))


def _resolve_symbols(conn: sqlite3.Connection, args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return list(args.symbols)
    symbols = db.get_all_symbols(conn)
    if args.limit:
        symbols = symbols[: args.limit]
    return symbols


def cmd_fetch_hist(conn: sqlite3.Connection, cfg: Config, args: argparse.Namespace) -> None:
    symbols = _resolve_symbols(conn, args)
    if not symbols:
        logger.warning("fetch-hist: 标的列表为空，先跑 fetch-list")
        return

    total = len(symbols)
    for i, symbol in enumerate(symbols, start=1):
        if args.full:
            start_date = "19700101"
        else:
            last = db.get_last_trade_date(conn, symbol)
            if last:
                start_date = (datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
            else:
                start_date = "19700101"

        try:
            hist = fetch.with_retry(
                fetch.fetch_etf_hist,
                symbol,
                start_date=start_date,
                adjust=cfg.adjust,
                max_retries=cfg.request.max_retries,
                backoff_sec=cfg.request.retry_backoff_sec,
            )
            n = db.upsert_daily_rows(conn, symbol, hist)
            last_date = hist["trade_date"].iloc[-1] if not hist.empty else db.get_last_trade_date(conn, symbol)
            db.set_fetch_state(conn, symbol, last_date, _now_iso(), status="ok")
            conn.commit()
            logger.info("[%d/%d] %s: 新增/更新 %d 行 (start=%s)", i, total, symbol, n, start_date)
        except Exception as exc:
            db.set_fetch_state(conn, symbol, db.get_last_trade_date(conn, symbol), _now_iso(),
                                status="error", error_message=str(exc))
            conn.commit()
            logger.error("[%d/%d] %s: 拉取失败 - %s", i, total, symbol, exc)

        if i < total:
            fetch.sleep_between_requests(cfg.request.sleep_min_sec, cfg.request.sleep_max_sec)


def cmd_build_pool(conn: sqlite3.Connection, cfg: Config) -> None:
    from . import pool

    result = pool.build_pool(conn, cfg.pool_filter)
    result.to_csv(cfg.output_pool_csv, index=False, encoding="utf-8-sig")
    n_pool = int(result["in_pool"].sum()) if not result.empty else 0
    logger.info("build-pool: 共 %d 只ETF，入池 %d 只，清单已写入 %s", len(result), n_pool, cfg.output_pool_csv)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="BlindTape 数据层 CLI")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("fetch-list", help="拉取全市场ETF列表")

    p_hist = sub.add_parser("fetch-hist", help="拉取/增量更新历史日线")
    p_hist.add_argument("--full", action="store_true", help="忽略增量状态，全量重新拉取")
    p_hist.add_argument("--symbols", nargs="+", help="只拉取指定代码")
    p_hist.add_argument("--limit", type=int, help="只拉取前N只（调试用）")

    sub.add_parser("build-pool", help="按过滤规则生成可训练标的池清单")

    p_all = sub.add_parser("run-all", help="全流程：fetch-list -> fetch-hist -> build-pool")
    p_all.add_argument("--full", action="store_true", help="fetch-hist 阶段全量重新拉取")
    p_all.add_argument("--limit", type=int, help="fetch-hist 阶段只拉取前N只（调试用）")

    args = parser.parse_args()
    cfg = load_config(args.config)
    db.init_db(cfg.db_path)

    with db.connect(cfg.db_path) as conn:
        if args.command == "fetch-list":
            cmd_fetch_list(conn, cfg)
        elif args.command == "fetch-hist":
            cmd_fetch_hist(conn, cfg, args)
        elif args.command == "build-pool":
            cmd_build_pool(conn, cfg)
        elif args.command == "run-all":
            cmd_fetch_list(conn, cfg)
            hist_args = argparse.Namespace(full=args.full, symbols=None, limit=args.limit)
            cmd_fetch_hist(conn, cfg, hist_args)
            cmd_build_pool(conn, cfg)


if __name__ == "__main__":
    main()
