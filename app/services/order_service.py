import logging
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.setting import Setting
from app.models.point_log import PointLog

logger = logging.getLogger(__name__)


def award_transaction_points(user_id, trx_ref_id):
    """Memberikan reward poin transaksi sukses kepada member secara idempoten & komisi downline ke upline VIP."""
    try:
        if not user_id:
            return

        desc = f"Reward transaksi {trx_ref_id}"
        existing = PointLog.query.filter_by(
            user_id=user_id, type="EARN_TRX", description=desc
        ).first()
        if not existing:
            st = Setting.query.filter_by(key="point_reward_per_trx").first()
            pts_reward = (
                int(st.value) if st and st.value and st.value.isdigit() else 1
            )
            if pts_reward > 0:
                user = User.query.get(user_id)
                if user:
                    user.points = (user.points or 0) + pts_reward
                    plog = PointLog(
                        user_id=user.id,
                        type="EARN_TRX",
                        points=pts_reward,
                        balance_added=0.0,
                        description=desc,
                    )
                    db.session.add(plog)
                    db.session.commit()
                    logger.info(
                        f"[POIN] Member {user.id} +{pts_reward} Pts for trx {trx_ref_id}"
                    )

        # Berikan komisi ke Upline VIP jika transaksi ini dilakukan oleh Downline
        try:
            from app.models.transaction import Transaction
            from app.services.commission_service import (
                award_downline_commission,
            )

            trx_obj = Transaction.query.filter_by(ref_id=trx_ref_id).first()
            if trx_obj and trx_obj.status == "SUCCESS":
                award_downline_commission(trx_obj)
        except Exception as comm_err:
            logger.error(
                f"[COMMISSION ERROR] Gagal award komisi downline: {comm_err}"
            )

    except Exception as err:
        db.session.rollback()
        logger.error(f"[POIN ERROR] Error awarding points: {err}")


def process_paid_order(trx):
    """
    Menjalankan pemrosesan otomatis setelah transaksi berstatus PAID.
    Berlaku seragam dan idempoten untuk seluruh gateway pembayaran dan In-House DANA QRIS.
    """
    if not trx:
        return False

    trx.payment_status = "PAID"

    # 1. Jika ini transaksi deposit saldo
    if trx.sku_code in ["DEPOSIT_SALDO", "DEPOSIT_MANUAL"]:
        user = User.query.filter_by(id=trx.user_id).with_for_update().first()
        if user and trx.status != "SUCCESS":
            old_bal = float(user.balance or 0.0)
            user.balance += trx.amount
            trx.status = "SUCCESS"
            logger.info(f"[DEPOSIT] User {user.id} balance +Rp {trx.amount}")
            try:
                from app.services.balance_notification_service import (
                    check_and_notify_low_balance,
                )

                check_and_notify_low_balance(user.id, old_bal, user.balance)
            except Exception:
                pass

    # 2. Jika transaksi produk pascabayar / prabayar, trigger Digiflazz
    elif trx.status in ["UNPAID", "PENDING", "PROCESSING"]:
        try:
            bebas_sku_list = [
                "post685480",
                "post685481",
                "post685482",
                "post685483",
                "post685485",
                "post706873",
            ]
            is_pasca_flow = (trx.is_prepaid is False) or (
                trx.sku_code in bebas_sku_list
            )

            if is_pasca_flow:
                from app.services.digiflazz import (
                    pay_pasca,
                    apply_digiflazz_seller_metadata,
                )
                from app.services.provider_helper import (
                    sanitize_public_sn_message,
                )

                ok_pay, res_pay, msg_pay = pay_pasca(
                    trx.sku_code, trx.target_number, trx.ref_id
                )
                apply_digiflazz_seller_metadata(trx, res_pay)
                if ok_pay:
                    rc_pay = str(res_pay.get("rc", "")).strip()
                    if rc_pay == "00":
                        trx.status = "SUCCESS"
                        trx.sn = res_pay.get("sn", "")
                        award_transaction_points(trx.user_id, trx.ref_id)
                    else:
                        trx.status = "PROCESSING"
                else:
                    trx.status = "FAILED"
                    trx.sn = sanitize_public_sn_message(msg_pay)
                    # Auto refund saldo jika bayar QRIS tapi provider gagal
                    _auto_refund_on_failure(trx)
            else:
                from app.services.digiflazz import (
                    create_transaction,
                    apply_digiflazz_seller_metadata,
                )
                from app.services.provider_helper import (
                    sanitize_public_sn_message,
                )

                product = Product.query.filter_by(sku_code=trx.sku_code).first()
                sku_to_order = product.sku_code if product else trx.sku_code
                digi_res = create_transaction(
                    sku_to_order, trx.target_number, trx.ref_id
                )
                d_data = (
                    digi_res.get("data")
                    if isinstance(digi_res, dict)
                    and isinstance(digi_res.get("data"), dict)
                    else {}
                )
                apply_digiflazz_seller_metadata(trx, d_data, product)
                digi_status = str(d_data.get("status", "")).lower()
                rc = str(d_data.get("rc", "")).strip()

                if (
                    "sukses" in digi_status
                    or "success" in digi_status
                    or rc == "00"
                ):
                    trx.status = "SUCCESS"
                    trx.sn = d_data.get("sn", "")
                    award_transaction_points(trx.user_id, trx.ref_id)
                elif "gagal" in digi_status or "failed" in digi_status or rc in [
                    "01",
                    "41",
                    "42",
                    "50",
                    "52",
                ]:
                    trx.status = "FAILED"
                    raw_msg = d_data.get("message", "Gagal dari provider")
                    trx.sn = sanitize_public_sn_message(raw_msg, rc=rc)
                    # Auto refund saldo jika bayar QRIS tapi provider gagal
                    _auto_refund_on_failure(trx)
                else:
                    trx.status = "PROCESSING"
        except Exception as e:
            logger.error(
                f"[ERROR] Digiflazz trigger after payment: {str(e)}"
            )
            trx.status = "PENDING"

    trx.updated_at = db.func.now()
    db.session.commit()

    try:
        from app.services.telegram_service import async_send_trx_notification

        title_status = (
            "PEMBAYARAN DITERIMA & SUKSES"
            if trx.status == "SUCCESS"
            else "PEMBAYARAN DITERIMA (DIPROSES)"
        )
        async_send_trx_notification(trx, title=title_status)
    except Exception as e_tg:
        logger.error(f"[TELEGRAM NOTIF ERROR] {e_tg}")

    return True


def _auto_refund_on_failure(trx):
    """
    Jika transaksi berbayar QRIS/Gateway gagal di level provider,
    kembalikan uang ke saldo akun user secara otomatis agar dana pelanggan 100% aman.
    """
    try:
        if (trx.payment_method or "").upper() in ["QRIS", "DANA_INHOUSE", "PAKASIR", "PAYMENTKITA"]:
            user = User.query.filter_by(id=trx.user_id).with_for_update().first()
            if user:
                user.balance = (user.balance or 0.0) + float(trx.amount or 0.0)
                sn_note = f"{trx.sn or ''} (Refund Rp {trx.amount:,.0f} telah dikembalikan ke Saldo Akun)"
                trx.sn = sn_note[:255]
                logger.info(
                    f"[AUTO-REFUND QRIS] Ref: {trx.ref_id} gagal di provider -> Saldo user #{user.id} +Rp {trx.amount:,.0f}"
                )
    except Exception as e_ref:
        logger.error(f"[AUTO-REFUND ERROR] {e_ref}")
