import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const session = new Supabase.ai.Session("gte-small");

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return Response.json({ error: "Method not allowed" }, { status: 405 });
  }

  try {
    const { input } = await req.json();
    if (typeof input !== "string" || !input.trim() || input.length > 16_000) {
      return Response.json({ error: "input must be a non-empty string under 16,000 characters" }, { status: 400 });
    }

    const embedding = await session.run(input, { mean_pool: true, normalize: true });
    return Response.json({ embedding }, {
      headers: { "Cache-Control": "public, max-age=86400" },
    });
  } catch (error) {
    console.error("Embedding generation failed", error);
    return Response.json({ error: "Embedding generation failed" }, { status: 500 });
  }
});
