
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <queue>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>
#include <cstdio>
#include <utility>

namespace fs = std::filesystem;
using U8 = uint8_t;
using U16 = uint16_t;
using U32 = uint32_t;
using U64 = uint64_t;

static const fs::path BASE = "/sdcard/Download/BlackMIDI_Merger";
static const fs::path INPUT = BASE / "input";
static const fs::path OUTPUT = BASE / "output";
static const fs::path TEMP = BASE / "temp";
static const fs::path DEST = OUTPUT / "BlackMIDI_Merged.mid";
static const fs::path TMPFILE = TEMP / "merged.tmp";
static constexpr U64 MAX_VLQ = 0x0FFFFFFFULL;
static constexpr size_t BUFFER = 1024 * 1024;

static void fail(const std::string& s) {
    throw std::runtime_error(s);
}

static std::string lower(std::string s) {
    for (char& c : s)
        c = static_cast<char>(
            std::tolower(static_cast<unsigned char>(c))
        );
    return s;
}

static U16 be16(const U8* p) {
    return (U16(p[0]) << 8) | U16(p[1]);
}

static U32 be32(const U8* p) {
    return (U32(p[0]) << 24) | (U32(p[1]) << 16) |
           (U32(p[2]) << 8) | U32(p[3]);
}

static void put16(std::ostream& o, U16 v) {
    U8 b[2] = {U8(v >> 8), U8(v)};
    o.write(reinterpret_cast<const char*>(b), 2);
}

static void put32(std::ostream& o, U32 v) {
    U8 b[4] = {
        U8(v >> 24), U8(v >> 16), U8(v >> 8), U8(v)
    };
    o.write(reinterpret_cast<const char*>(b), 4);
}

static std::vector<U8> enc_vlq(U64 v) {
    if (v > MAX_VLQ)
        fail("Delta time outside MIDI VLQ range");

    U8 b[4];
    int n = 0;
    b[n++] = U8(v & 127);
    while ((v >>= 7) != 0)
        b[n++] = U8((v & 127) | 128);

    std::vector<U8> out;
    while (n)
        out.push_back(b[--n]);
    return out;
}

static void write_vlq(std::ostream& o, U64 v) {
    auto b = enc_vlq(v);
    o.write(reinterpret_cast<const char*>(b.data()), b.size());
}

struct TrackInfo {
    U64 start = 0;
    U64 length = 0;
};

struct Part {
    fs::path path;
    int number = 0;
    U16 division = 0;
    U64 first = std::numeric_limits<U64>::max();
    U64 last = 0;
    std::vector<TrackInfo> tracks;
};

struct Event {
    U64 tick = 0;
    std::vector<U8> data;
    int note = 0;
};

class Reader {
    std::ifstream f;
    U64 end = 0;
    U64 tick = 0;
    U8 running = 0;

    U8 byte() {
        char c;
        if (!f.get(c))
            fail("Unexpected end of MIDI data");
        return U8(static_cast<unsigned char>(c));
    }

    std::vector<U8> bytes(U64 n) {
        if (n > end - static_cast<U64>(f.tellg()))
            fail("Event exceeds track boundary");

        std::vector<U8> b(static_cast<size_t>(n));
        if (n && !f.read(reinterpret_cast<char*>(b.data()),
                         static_cast<std::streamsize>(n)))
            fail("Unexpected end of MIDI data");
        return b;
    }

    U64 vlq() {
        U64 v = 0;
        for (int i = 0; i < 4; ++i) {
            U8 b = byte();
            v = (v << 7) | (b & 127);
            if (!(b & 128))
                return v;
        }
        fail("Invalid MIDI VLQ");
        return 0;
    }

public:
    Reader(const fs::path& path, const TrackInfo& t)
        : f(path, std::ios::binary),
          end(t.start + t.length) {
        f.rdbuf()->pubsetbuf(nullptr, 0);
        if (!f)
            fail("Cannot open MIDI file: " + path.string());

        f.seekg(static_cast<std::streamoff>(t.start));
        if (!f)
            fail("Cannot seek MIDI track");
    }

    bool next(Event& e) {
        if (static_cast<U64>(f.tellg()) >= end)
            return false;

        U64 delta = vlq();
        if (tick > std::numeric_limits<U64>::max() - delta)
            fail("MIDI tick overflow");
        tick += delta;

        U8 b = byte();
        U8 status;
        bool has_first = b < 128;
        U8 first = b;

        if (has_first) {
            if (!running)
                fail("Invalid MIDI running status");
            status = running;
        } else {
            status = b;
        }

        e.tick = tick;
        e.note = 0;
        e.data.clear();

        if (status == 0xFF) {
            running = 0;
            U8 type = byte();
            U64 n = vlq();
            auto payload = bytes(n);

            if (type == 0x2F)
                return false;

            e.data.push_back(0xFF);
            e.data.push_back(type);
            auto len = enc_vlq(n);
            e.data.insert(e.data.end(), len.begin(), len.end());
            e.data.insert(e.data.end(), payload.begin(), payload.end());
            return true;
        }

        if (status == 0xF0 || status == 0xF7) {
            running = 0;
            U64 n = vlq();
            auto payload = bytes(n);

            e.data.push_back(status);
            auto len = enc_vlq(n);
            e.data.insert(e.data.end(), len.begin(), len.end());
            e.data.insert(e.data.end(), payload.begin(), payload.end());
            return true;
        }

        if (status >= 0xF0)
            fail("Unsupported system MIDI event");

        running = status;
        U8 kind = status & 0xF0;
        int count = (kind == 0xC0 || kind == 0xD0) ? 1 : 2;

        U8 a = has_first ? first : byte();
        U8 c = 0;
        if (count == 2)
            c = byte();

        if (a >= 128 || (count == 2 && c >= 128))
            fail("Invalid MIDI channel data");

        e.data.push_back(status);
        e.data.push_back(a);
        if (count == 2)
            e.data.push_back(c);

        if (kind == 0x90 && count == 2 && c != 0)
            e.note = 1;
        else if (kind == 0x80 ||
                 (kind == 0x90 && count == 2 && c == 0))
            e.note = -1;

        if (static_cast<U64>(f.tellg()) > end)
            fail("Event exceeds track boundary");

        return true;
    }
};

static int part_number(const fs::path& p) {
    static const std::regex r(
        R"(\bPT[\s_-]*(\d+)\b)",
        std::regex::icase
    );

    std::smatch m;
    std::string s = p.stem().string();
    if (!std::regex_search(s, m, r))
        return -1;

    try {
        long long n = std::stoll(m[1].str());
        if (n < 0 || n > std::numeric_limits<int>::max())
            return -1;
        return static_cast<int>(n);
    } catch (...) {
        return -1;
    }
}

static std::vector<fs::path> find_parts() {
    std::vector<fs::path> paths;

    for (const auto& e : fs::directory_iterator(INPUT)) {
        if (!e.is_regular_file())
            continue;

        std::string ext = lower(e.path().extension().string());
        if (ext != ".mid" && ext != ".midi")
            continue;

        if (part_number(e.path()) >= 0)
            paths.push_back(e.path());
    }

    std::sort(paths.begin(), paths.end(),
        [](const fs::path& a, const fs::path& b) {
            int na = part_number(a);
            int nb = part_number(b);
            if (na != nb)
                return na < nb;
            return lower(a.filename().string()) <
                   lower(b.filename().string());
        });

    return paths;
}

static Part scan(const fs::path& path) {
    std::ifstream f(path, std::ios::binary);
    f.rdbuf()->pubsetbuf(nullptr, 0);
    if (!f)
        fail("Cannot open: " + path.string());

    f.seekg(0, std::ios::end);
    auto file_end = f.tellg();
    if (file_end < 0)
        fail("Cannot determine file size");
    U64 file_size = static_cast<U64>(file_end);
    f.seekg(0);

    auto read_exact = [&](U64 n) -> std::vector<U8> {
        if (n > file_size - static_cast<U64>(f.tellg()))
            fail("Unexpected end of file");
        std::vector<U8> b(static_cast<size_t>(n));
        if (n && !f.read(reinterpret_cast<char*>(b.data()),
                         static_cast<std::streamsize>(n)))
            fail("Unexpected end of file");
        return b;
    };

    if (read_exact(4) != std::vector<U8>({'M','T','h','d'}))
        fail("Missing MIDI header");

    U32 header_size = be32(read_exact(4).data());
    if (header_size < 6)
        fail("Invalid MIDI header");

    auto h = read_exact(header_size);
    U16 format = be16(h.data());
    U16 count = be16(h.data() + 2);
    U16 division = be16(h.data() + 4);

    if (format > 1 || count == 0 || division == 0 ||
        (division & 0x8000))
        fail("Unsupported MIDI format or time division");

    Part p;
    p.path = path;
    p.number = part_number(path);
    p.division = division;

    for (U16 i = 0; i < count; ++i) {
        if (read_exact(4) != std::vector<U8>({'M','T','r','k'}))
            fail("Missing MIDI track");

        U32 len = be32(read_exact(4).data());
        U64 start = static_cast<U64>(f.tellg());

        if (start > file_size || len > file_size - start)
            fail("Track exceeds file size");

        p.tracks.push_back({start, len});

        Reader r(path, p.tracks.back());
        Event e;
        while (r.next(e)) {
            if (e.note == 1)
                p.first = std::min(p.first, e.tick);
            else if (e.note == -1)
                p.last = std::max(p.last, e.tick);
        }

        f.seekg(static_cast<std::streamoff>(start + len));
    }

    return p;
}

struct Node {
    Event event;
    size_t track;
};

struct NodeCompare {
    bool operator()(const Node& a, const Node& b) const {
        if (a.event.tick != b.event.tick)
            return a.event.tick > b.event.tick;
        return a.track > b.track;
    }
};

static void write_track(
    std::ostream& out,
    const Part& p,
    U64 shift
) {
    out.write("MTrk", 4);
    auto length_pos = out.tellp();
    put32(out, 0);
    auto data_start = out.tellp();

    std::vector<std::unique_ptr<Reader>> readers;
    readers.reserve(p.tracks.size());

    std::priority_queue<Node, std::vector<Node>, NodeCompare> queue;

    for (size_t i = 0; i < p.tracks.size(); ++i) {
        readers.emplace_back(
            std::make_unique<Reader>(p.path, p.tracks[i])
        );

        Event e;
        if (readers.back()->next(e))
            queue.push({std::move(e), i});
    }

    U64 previous = 0;
    U64 end_tick = shift + (p.last - p.first);

    while (!queue.empty()) {
        Node node = queue.top();
        queue.pop();

        Event& e = node.event;
        if (e.tick > p.last)
            break;

        U64 tick = e.tick >= p.first
            ? e.tick - p.first + shift
            : shift;

        if (tick < previous)
            fail("Events are not time ordered");

        U64 delta = tick - previous;

        while (delta > MAX_VLQ) {
            write_vlq(out, MAX_VLQ);
            const U8 spacer[] = {0xFF, 0x7F, 0x00};
            out.write(reinterpret_cast<const char*>(spacer), 3);
            delta -= MAX_VLQ;
            previous += MAX_VLQ;
        }

        write_vlq(out, delta);
        out.write(
            reinterpret_cast<const char*>(e.data.data()),
            static_cast<std::streamsize>(e.data.size())
        );
        previous = tick;

        Event next;
        if (readers[node.track]->next(next))
            queue.push({std::move(next), node.track});
    }

    if (end_tick < previous)
        end_tick = previous;

    write_vlq(out, end_tick - previous);
    const U8 eot[] = {0xFF, 0x2F, 0x00};
    out.write(reinterpret_cast<const char*>(eot), 3);

    auto end_pos = out.tellp();
    if (end_pos < data_start)
        fail("Output position error");

    U64 length = static_cast<U64>(end_pos - data_start);
    if (length > 0xFFFFFFFFULL)
        fail("MIDI track exceeds 4 GB");

    out.seekp(length_pos);
    put32(out, static_cast<U32>(length));
    out.seekp(end_pos);

    if (!out)
        fail("Output write failed");
}

int main() {
    auto started = std::chrono::steady_clock::now();

    try {
        fs::create_directories(INPUT);
        fs::create_directories(OUTPUT);
        fs::create_directories(TEMP);

        auto paths = find_parts();

        if (paths.empty()) {
            std::cout << "No PT MIDI files found: "
                      << INPUT << '\n';
            return 1;
        }

        std::cout << "Parts found: " << paths.size() << '\n';

        std::vector<Part> parts;
        U16 division = 0;

        for (size_t i = 0; i < paths.size(); ++i) {
            try {
                Part p = scan(paths[i]);

                if (p.first == std::numeric_limits<U64>::max()) {
                    std::cout << "Skipping no-note file: "
                              << p.path.filename() << '\n';
                    continue;
                }

                if (division == 0)
                    division = p.division;
                else if (division != p.division)
                    fail("Different MIDI time divisions");

                parts.push_back(std::move(p));

                std::cout << "Scanned: " << paths[i].filename()
                          << ' ' << i + 1 << '/' << paths.size()
                          << '\n';
            } catch (const std::exception& e) {
                std::cerr << "SCAN ERROR: " << paths[i].filename()
                          << " : " << e.what() << '\n';
                return 1;
            }
        }

        if (parts.empty()) {
            std::cout << "No usable MIDI parts\n";
            return 1;
        }

        if (parts.size() > 65535)
            fail("Too many output tracks");

        U64 shift = 0;

        {
            std::ofstream out(TMPFILE, std::ios::binary | std::ios::trunc);
            out.rdbuf()->pubsetbuf(nullptr, 0);
            if (!out)
                fail("Cannot create temporary output");

            out.write("MThd", 4);
            put32(out, 6);
            put16(out, 1);
            put16(out, static_cast<U16>(parts.size()));
            put16(out, division);

            for (size_t i = 0; i < parts.size(); ++i) {
                const Part& p = parts[i];

                std::cout << "Merging: " << p.path.filename()
                          << ' ' << i + 1 << '/' << parts.size()
                          << '\n';

                write_track(out, p, shift);

                U64 duration = p.last - p.first;
                if (shift > std::numeric_limits<U64>::max() - duration)
                    fail("Timeline overflow");

                shift += duration;
                out.flush();
                if (!out)
                    fail("Output write failed");
            }

            out.close();
            if (!out)
                fail("Failed to close output");
        }

        {
            std::ifstream f(TMPFILE, std::ios::binary);
            U8 h[14];
            if (!f.read(reinterpret_cast<char*>(h), 14))
                fail("Output validation failed");

            if (std::string(reinterpret_cast<char*>(h), 4) != "MThd" ||
                be32(h + 4) != 6 ||
                be16(h + 8) != 1 ||
                be16(h + 10) != parts.size() ||
                be16(h + 12) != division)
                fail("Output header validation failed");
        }

        if (std::rename(TMPFILE.c_str(), DEST.c_str()) != 0)
            fail("Cannot replace destination: " +
                 std::string(std::strerror(errno)));

        auto elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - started
        ).count();

        std::cout << "SUCCESS: " << DEST << '\n';
        std::cout << "Output size: "
                  << double(fs::file_size(DEST)) / 1048576.0
                  << " MB\n";
        std::cout << "Elapsed: " << elapsed << " seconds\n";

        return 0;

    } catch (const std::exception& e) {
        std::cerr << "FAILED: " << e.what() << '\n';
        std::cerr << "Temporary file: " << TMPFILE << '\n';
        return 1;
    }
}
