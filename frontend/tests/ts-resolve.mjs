/* Minimal ESM resolve hook so Node can import SEEK's TypeScript sources
 * directly (`--experimental-strip-types`) without bundler-style extensionless
 * specifiers breaking at runtime. Test infrastructure only - never bundled.
 */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    const notFound = error?.code === 'ERR_MODULE_NOT_FOUND';
    const relative = specifier.startsWith('./') || specifier.startsWith('../');
    const hasExtension = /\.[cm]?[jt]sx?$/.test(specifier);
    if (notFound && relative && !hasExtension) {
      return nextResolve(`${specifier}.ts`, context);
    }
    throw error;
  }
}