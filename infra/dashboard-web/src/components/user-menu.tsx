"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Shield } from "lucide-react";

import { useLocale, useT } from "@/components/locale-provider";
import { auth, roleLabel } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function useMe() {
  return useQuery({ queryKey: ["auth", "me"], queryFn: auth.me, staleTime: 60_000 });
}

export function UserMenu({ className }: { className?: string }) {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const { locale } = useLocale();
  const t = useT();
  if (!me) return null;
  const logout = async () => {
    try {
      await auth.logout();
    } finally {
      qc.clear();
      window.location.href = "/";
    }
  };
  const name = me.display_name || me.username;
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {me.role === "admin" && (
        <Link
          href="/admin/users"
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          title={t("Users and API keys", "用户与 API 密钥")}
        >
          <Shield className="h-4 w-4" />
          <span className="sr-only">{t("Users", "用户")}</span>
        </Link>
      )}
      <Link
        href="/account"
        className="flex h-8 items-center gap-2 rounded-md px-2 text-sm hover:bg-accent"
        title={t("Account, password and API keys", "账户、密码与 API 密钥")}
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase text-secondary-foreground">
          {name.slice(0, 1)}
        </span>
        <span className="hidden font-medium sm:inline">{name}</span>
        <span className="hidden text-xs text-muted-foreground md:inline">{roleLabel(me.role, locale)}</span>
      </Link>
      <button
        type="button"
        onClick={logout}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        title={t("Sign out", "退出登录")}
      >
        <LogOut className="h-4 w-4" />
        <span className="sr-only">{t("Sign out", "退出登录")}</span>
      </button>
    </div>
  );
}
