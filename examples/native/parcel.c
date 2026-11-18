/* Original deterministic parcel-pricing fixture; not the blind P04 assessment. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

static int available = 12;
static int reserved = 0;
static int service_zone = 0;

int quote_parcel(int grams, int priority, int zone) {
    if (grams <= 0 || grams > 20000 || priority < 0 || priority > 1) return -1;
    int blocks = (grams + 499) / 500;
    int fee = 250 + blocks * 75;
    if (zone == 2) fee += 180;
    if (priority) fee += 300 + blocks * 20;
    return fee;
}

int reserve_parcels(int count) {
    if (count <= 0 || count > available) return -1;
    available -= count;
    reserved += count;
    return reserved;
}

int dispatch_command(const char *verb, int a, int b) {
    if (!strcmp(verb, "quote")) {
        int fee = quote_parcel(a, b, service_zone);
        if (fee < 0) { puts("{\"ok\":false,\"error\":\"weight-or-priority\"}"); return 1; }
        printf("{\"ok\":true,\"cents\":%d,\"zone\":%d}\n", fee, service_zone);
    } else if (!strcmp(verb, "reserve")) {
        if (reserve_parcels(a) < 0) { puts("{\"ok\":false,\"error\":\"stock\"}"); return 1; }
        printf("{\"ok\":true,\"available\":%d,\"reserved\":%d}\n", available, reserved);
    } else if (!strcmp(verb, "cancel")) {
        if (a <= 0 || a > reserved) { puts("{\"ok\":false,\"error\":\"reservation\"}"); return 1; }
        available += a; reserved -= a;
        printf("{\"ok\":true,\"available\":%d,\"reserved\":%d}\n", available, reserved);
    } else if (!strcmp(verb, "state")) {
        printf("{\"ok\":true,\"available\":%d,\"reserved\":%d}\n", available, reserved);
    } else { puts("{\"ok\":false,\"error\":\"operation\"}"); return 1; }
    return 0;
}

int main(int argc, char **argv) {
    FILE *input = argc > 1 ? fopen(argv[1], "r") : stdin;
    if (!input) { fputs("input-file\n", stderr); return 2; }
    const char *env = getenv("TRACEANCHOR_PARCEL_ZONE");
    if (env && !strcmp(env, "remote")) service_zone = 2;
    char line[128], verb[24];
    while (fgets(line, sizeof(line), input)) {
        int a = 0, b = 0;
        if (sscanf(line, "%23s %d %d", verb, &a, &b) >= 1) dispatch_command(verb, a, b);
    }
    return 0;
}
