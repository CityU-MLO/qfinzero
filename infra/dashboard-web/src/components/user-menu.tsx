"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, LogOut, Shield, User } from "lucide-react";

import { auth, ROLE_LABEL } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function useMe() {
  return useQuery({ queryKey: ["auth", "me"], queryFn: auth.me, staleTime: 60_000 });
}

export function UserMenu({ className }: { className?: string }) {
  const { data: me } = useMe();
  const qc = useQueryClient();
  if (!me) return null;
  const logout = async () => {
    try {
      await auth.logout();
    } finally {
      qc.clear();
      window.location.href = "/";
    }
  };
  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      {me.role === "admin" && (
        <Link
          href="/admin/users"
          className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          title="Users and keys"
        >
          <Shield className="h-4 w-4" />
          Users
        </Link>
      )}
      <Link
        href="/account"
        className="flex items-center gap-2 rounded-lg border bg-white/70 px-3 py-1.5 text-sm hover:bg-accent"
        title="Account, password and API keys"
      >
        <User className="h-4 w-4 text-muted-foreground" />
        <span className="font-medium">{me.display_name || me.username}</span>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-secondary-foreground">
          {ROLE_LABEL[me.role]}
        </span>
        <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
      </Link>
      <button
        type="button"
        onClick={logout}
        className="flex items-center gap-1 rounded-lg px-2.5 py-2 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
        title="Sign out"
      >
        <LogOut className="h-4 w-4" />
        <span className="sr-only">Sign out</span>
      </button>
    </div>
  );
}
