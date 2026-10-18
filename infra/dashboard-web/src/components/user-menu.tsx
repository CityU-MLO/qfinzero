"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut, Shield } from "lucide-react";

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
  const name = me.display_name || me.username;
  return (
    <div className={cn("flex items-center gap-1", className)}>
      {me.role === "admin" && (
        <Link
          href="/admin/users"
          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          title="Users and API keys"
        >
          <Shield className="h-4 w-4" />
          <span className="sr-only">Users</span>
        </Link>
      )}
      <Link
        href="/account"
        className="flex h-8 items-center gap-2 rounded-md px-2 text-sm hover:bg-accent"
        title="Account, password and API keys"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase text-secondary-foreground">
          {name.slice(0, 1)}
        </span>
        <span className="hidden font-medium sm:inline">{name}</span>
        <span className="hidden text-xs text-muted-foreground md:inline">{ROLE_LABEL[me.role]}</span>
      </Link>
      <button
        type="button"
        onClick={logout}
        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
        title="Sign out"
      >
        <LogOut className="h-4 w-4" />
        <span className="sr-only">Sign out</span>
      </button>
    </div>
  );
}
