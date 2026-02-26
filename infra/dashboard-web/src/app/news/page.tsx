import { NewsBrowser } from "@/components/news/news-browser";

export default function NewsPage() {
  return (
    <main className="space-y-4">
      <section>
        <h2 className="text-xl font-semibold">MongoDB News Browser</h2>
        <p className="text-sm text-muted-foreground">
          Query by ticker/time/publisher/keyword, inspect rows, and export current result set.
        </p>
      </section>
      <NewsBrowser />
    </main>
  );
}
