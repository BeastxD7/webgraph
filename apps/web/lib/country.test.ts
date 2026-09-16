import assert from "node:assert/strict";
import { test } from "node:test";

import { countryOf, hostOf } from "./country.ts";

test("country-code TLDs, with their second levels", () => {
  assert.equal(countryOf("vtu.ac.in")?.code, "in");
  assert.equal(countryOf("www.gov.uk")?.code, "uk");
  assert.equal(countryOf("shop.co.uk")?.name, "United Kingdom");
  assert.equal(countryOf("example.com.au")?.code, "au");
  assert.equal(countryOf("heise.de")?.code, "de");
  assert.equal(countryOf("sode-edu.in")?.code, "in");
});

test("the US-only generic domains", () => {
  assert.equal(countryOf("docs.python.org"), null);
  assert.equal(countryOf("mit.edu")?.code, "us");
  assert.equal(countryOf("nasa.gov")?.code, "us");
});

test("no country for a generic TLD or a bare word", () => {
  assert.equal(countryOf("example.com"), null);
  assert.equal(countryOf("localhost"), null);
  assert.equal(countryOf("example.xyz"), null);
});

test("hostOf takes what a person types", () => {
  assert.equal(hostOf("vtu.ac.in/about"), "vtu.ac.in");
  assert.equal(hostOf("https://docs.python.org/3/"), "docs.python.org");
  assert.equal(hostOf("  gov.uk/browse "), "gov.uk");
  assert.equal(hostOf("not a url"), null);
  assert.equal(hostOf(""), null);
});
