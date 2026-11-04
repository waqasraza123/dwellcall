import argparse
import json
from uuid import UUID

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dwellcall.billing.catalog import PLANS, STRIPE_PRODUCT_ID
from dwellcall.billing.gateway import StripeGateway
from dwellcall.billing.portal import setup_portal_configurations
from dwellcall.billing.service import BillingService
from dwellcall.database.connection import create_database_engine
from dwellcall.database.models.billing import BillingAccount
from dwellcall.settings import ApiSettings


def setup_catalog(settings: ApiSettings) -> dict[str, str]:
    gateway = StripeGateway(settings)
    with gateway.client(translate_errors=False) as client:
        try:
            product = client.v1.products.retrieve(STRIPE_PRODUCT_ID)
        except stripe.InvalidRequestError as error:
            if error.http_status != 404:
                raise
            product = client.v1.products.create({
                "id": STRIPE_PRODUCT_ID, "name": "DwellCall subscription",
                "description": "Monthly DwellCall subscriptions.",
            }, options={"idempotency_key": "dwellcall:catalog:product:v1"})
        if not product.active:
            raise RuntimeError("The DwellCall product is archived; the owner must review it")
        price_ids: dict[str, str] = {}
        for plan in (PLANS["pro"], PLANS["team"]):
            lookup = f"dwellcall_{plan.key}_monthly_v1"
            prices = client.v1.prices.list({"lookup_keys": [lookup], "limit": 2})
            if len(prices.data) > 1:
                raise RuntimeError("Multiple prices match the managed lookup key")
            if prices.data:
                price = prices.data[0]
                if price.product != product.id or price.unit_amount != plan.amount or price.currency != "usd" or price.recurring is None or price.recurring.interval != "month" or price.recurring.interval_count != 1 or not price.active:
                    raise RuntimeError(f"Existing {plan.key} price does not match the agreed catalog")
            else:
                price = client.v1.prices.create({
                    "product": product.id, "currency": "usd", "unit_amount": plan.amount,
                    "recurring": {"interval": "month"}, "lookup_key": lookup,
                    "nickname": f"DwellCall {plan.name} monthly", "metadata": {"plan": plan.key},
                }, options={"idempotency_key": f"dwellcall:catalog:{plan.key}:v1"})
            price_ids[plan.key] = price.id
        return {"STRIPE_PRO_PRICE_ID": price_ids["pro"], "STRIPE_TEAM_PRICE_ID": price_ids["team"], **setup_portal_configurations(client, settings, price_ids)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Owner-operated DwellCall Stripe setup and reconciliation")
    parser.add_argument("command", choices=["setup", "reconcile", "bind-customer", "bind-checkout"])
    parser.add_argument("--account-id", type=UUID)
    parser.add_argument("--request-id", type=UUID)
    parser.add_argument("--customer-id")
    parser.add_argument("--session-id")
    parser.add_argument("--max-accounts", type=int, default=25, choices=range(1, 101))
    args = parser.parse_args()
    settings = ApiSettings()
    if args.command == "setup":
        print(json.dumps(setup_catalog(settings)))
        return
    if args.command == "bind-customer" and (not args.account_id or not args.customer_id or not args.customer_id.startswith("cus_")):
        parser.error("bind-customer requires --account-id UUID and --customer-id cus_...")
    if args.command == "bind-checkout" and (not args.request_id or not args.session_id or not args.session_id.startswith("cs_")):
        parser.error("bind-checkout requires --request-id UUID and --session-id cs_...")
    engine = create_database_engine(settings, service_name="billing-owner")
    try:
        sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
        service = BillingService(sessions, settings)
        if args.command == "bind-customer":
            service.bind_customer(args.account_id, args.customer_id)
            print(json.dumps({"bound": True}))
        elif args.command == "bind-checkout":
            service.bind_checkout(args.request_id, args.session_id)
            print(json.dumps({"bound": True}))
        else:
            with sessions() as session:
                query = select(BillingAccount.account_id).where(BillingAccount.customer_id.is_not(None))
                if args.account_id:
                    query = query.where(BillingAccount.account_id == args.account_id)
                identifiers = list(session.scalars(query.order_by(BillingAccount.last_synced_at.asc().nulls_first(), BillingAccount.account_id).limit(args.max_accounts)))
            for account_id in identifiers:
                service.refresh(account_id)
            print(json.dumps({"reconciled": len(identifiers)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
