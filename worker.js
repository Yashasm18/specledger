export default {
  async fetch(request, env) {
    if (env && env.ASSETS && typeof env.ASSETS.fetch === "function") {
      return await env.ASSETS.fetch(request);
    }
    return new Response("SpecLedger Cloudflare Edge Worker", { status: 200 });
  },
};
