from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import TextIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


SessionFactory = Callable[[], Session]


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _require_password(password: str) -> str:
    value = password.strip()
    if len(value) < 8:
        raise ValueError("Пароль должен содержать не менее 8 символов")
    return value


def _create_super_admin(
    db: Session,
    *,
    email: str,
    password: str,
) -> tuple[bool, bool]:
    """
    Returns:
      created: создан ли пользователь.
      elevated: был ли только что выдан флаг super-admin.
    """
    email_norm = _normalize_email(email)
    password_norm = _require_password(password)
    user = db.scalars(select(User).where(User.email == email_norm)).first()
    if user is None:
        user = User(
            email=email_norm,
            password_hash=hash_password(password_norm),
            is_super_admin=True,
        )
        db.add(user)
        db.commit()
        return True, True

    changed = False
    if not user.is_super_admin:
        user.is_super_admin = True
        changed = True
    if not user.password_hash:
        user.password_hash = hash_password(password_norm)
        changed = True
    if changed:
        db.add(user)
        db.commit()
    return False, changed


def _grant_super_admin(db: Session, *, email: str) -> bool:
    email_norm = _normalize_email(email)
    user = db.scalars(select(User).where(User.email == email_norm)).first()
    if user is None:
        raise ValueError("Пользователь не найден")
    if user.is_super_admin:
        return False
    user.is_super_admin = True
    db.add(user)
    db.commit()
    return True


def _revoke_super_admin(db: Session, *, email: str) -> bool:
    email_norm = _normalize_email(email)
    user = db.scalars(select(User).where(User.email == email_norm)).first()
    if user is None:
        raise ValueError("Пользователь не найден")
    if not user.is_super_admin:
        return False

    super_admins_total = db.scalar(
        select(func.count()).select_from(User).where(User.is_super_admin.is_(True))
    )
    if (super_admins_total or 0) <= 1:
        raise ValueError("Нельзя снять флаг у последнего супер-админа")

    user.is_super_admin = False
    db.add(user)
    db.commit()
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.admin_bootstrap",
        description="Bootstrap и управление супер-админами",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_create = subparsers.add_parser(
        "create-super-admin",
        help="Создать пользователя (если нет) и выдать super-admin",
    )
    p_create.add_argument("--email", required=True)
    p_create.add_argument("--password", required=True)

    p_grant = subparsers.add_parser(
        "grant-super-admin",
        help="Выдать super-admin существующему пользователю",
    )
    p_grant.add_argument("--email", required=True)

    p_revoke = subparsers.add_parser(
        "revoke-super-admin",
        help="Снять super-admin (с защитой от снятия последнего)",
    )
    p_revoke.add_argument("--email", required=True)
    return parser


def run(
    argv: list[str] | None = None,
    *,
    session_factory: SessionFactory = SessionLocal,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        with session_factory() as db:
            if args.command == "create-super-admin":
                created, elevated = _create_super_admin(
                    db, email=args.email, password=args.password
                )
                if created:
                    stdout.write("Создан пользователь и выдан флаг super-admin\n")
                elif elevated:
                    stdout.write("Пользователь обновлён: выдан флаг super-admin\n")
                else:
                    stdout.write("Без изменений: super-admin уже назначен\n")
                return 0

            if args.command == "grant-super-admin":
                changed = _grant_super_admin(db, email=args.email)
                if changed:
                    stdout.write("Флаг super-admin выдан\n")
                else:
                    stdout.write("Без изменений: super-admin уже назначен\n")
                return 0

            if args.command == "revoke-super-admin":
                changed = _revoke_super_admin(db, email=args.email)
                if changed:
                    stdout.write("Флаг super-admin снят\n")
                else:
                    stdout.write("Без изменений: у пользователя нет super-admin\n")
                return 0

        parser.error("Неизвестная команда")
    except ValueError as exc:
        stderr.write(f"Ошибка: {exc}\n")
        return 1

    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
