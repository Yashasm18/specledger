export default {
  async fetch(request, env) {
    try {
      if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
        return await env.ASSETS.fetch(request);
      }
      return new Response("SpecLedger Cloudflare Edge Worker", { status: 200 });
    } catch (err) {
      return new Response(`Worker Asset Error: ${err.message}`, { status: 500 });
    }
  },
};
