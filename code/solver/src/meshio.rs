//! OpenFOAM ascii 文件读取
//!
//! provenance：读取的是归档算例的 ascii 数据文件（polyMesh 的 points/faces/owner/
//! neighbour/boundary、0/ 场文件、constant/ 与 system/ 字典）——均为**数据/配置文件**，
//! 不是 OpenFOAM 实现源码（清洁室纪律 §2 只禁实现代码）。
//! 字典语法：OpenFOAM 用户手册的 FoamFile 字典格式（keyword value; / keyword { } / keyword (list);）。

use std::fs;
use std::path::Path;

use crate::mesh::{Mesh, Patch};

/// 字典条目：Word = "key value...;" 的 value 串（含 balanced 括号组）；Sub = 嵌套字典
#[derive(Debug, Clone)]
pub enum Entry {
    Word(String),
    Sub(Dict),
}

pub type Dict = Vec<(String, Entry)>;

impl Entry {
    /// 剥离开头的维度组 "[0 2 -1 0 0 0 0]" 与 "uniform" 前缀
    /// （OpenFOAM 条目 `keyword [dims] uniform value;`）
    fn strip_dims(w: &str) -> &str {
        let t = w.trim();
        let t = if let Some(rest) = t.strip_prefix('[') {
            if let Some(idx) = rest.find(']') {
                rest[idx + 1..].trim()
            } else {
                t
            }
        } else {
            t
        };
        t.strip_prefix("uniform").unwrap_or(t).trim()
    }

    pub fn word(&self) -> Result<&str, String> {
        match self {
            Entry::Word(w) => Ok(w),
            Entry::Sub(_) => Err("期望标量词条，得到子字典".into()),
        }
    }
    pub fn sub(&self) -> Result<&Dict, String> {
        match self {
            Entry::Sub(d) => Ok(d),
            Entry::Word(w) => Err(format!("期望子字典，得到词条 '{w}'")),
        }
    }
    /// value 串的第一个 token 解析为 f64（如 "uniform 80" → 80.0）
    pub fn f64(&self) -> Result<f64, String> {
        let w = Self::strip_dims(self.word()?);
        let t = w
            .split_whitespace()
            .next()
            .ok_or_else(|| "空 value".to_string())?;
        t.parse::<f64>().map_err(|e| format!("'{t}' 不是 f64: {e}"))
    }
    pub fn usize(&self) -> Result<usize, String> {
        let w = Self::strip_dims(self.word()?);
        let t = w
            .split_whitespace()
            .next()
            .ok_or_else(|| "空 value".to_string())?;
        t.parse::<usize>()
            .map_err(|e| format!("'{t}' 不是 usize: {e}"))
    }
    /// 解析 "(x y z)" / "uniform (x y z)" / "[dims] (x y z)" 为三元组
    pub fn vec3(&self) -> Result<[f64; 3], String> {
        let w = Self::strip_dims(self.word()?);
        let inner = w.trim();
        let inner = inner.strip_prefix("uniform").unwrap_or(inner).trim();
        let inner = inner
            .strip_prefix('(')
            .and_then(|s| s.strip_suffix(')'))
            .ok_or_else(|| format!("'{w}' 不是 (x y z) 向量"))?;
        let parts: Result<Vec<f64>, _> =
            inner.split_whitespace().map(|t| t.parse::<f64>()).collect();
        let parts = parts.map_err(|e| format!("'{w}' 向量解析失败: {e}"))?;
        if parts.len() != 3 {
            return Err(format!("'{w}' 向量分量数 = {} != 3", parts.len()));
        }
        Ok([parts[0], parts[1], parts[2]])
    }
}

/// 按 '.' 路径查找字典条目，如 "relaxationFactors.fields.p"
pub fn dict_get<'a>(d: &'a Dict, path: &str) -> Result<&'a Entry, String> {
    let keys: Vec<&str> = path.split('.').collect();
    let mut cur: &Dict = d;
    let mut val: Option<&Entry> = None;
    for (i, k) in keys.iter().enumerate() {
        let e = cur
            .iter()
            .find(|(key, _)| key == k)
            .ok_or_else(|| format!("字典键 '{k}' 未找到（路径 {path}）"))?;
        val = Some(&e.1);
        if i + 1 < keys.len() {
            cur = e.1.sub()?;
        }
    }
    val.ok_or_else(|| format!("空路径 {path}"))
}

struct Lexer<'a> {
    s: &'a [u8],
    pos: usize,
}

impl<'a> Lexer<'a> {
    fn new(s: &'a [u8]) -> Self {
        Lexer { s, pos: 0 }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.s.len() {
            let c = self.s[self.pos];
            if c.is_ascii_whitespace() {
                self.pos += 1;
            } else if c == b'/' && self.pos + 1 < self.s.len() && self.s[self.pos + 1] == b'/' {
                while self.pos < self.s.len() && self.s[self.pos] != b'\n' {
                    self.pos += 1;
                }
            } else if c == b'/' && self.pos + 1 < self.s.len() && self.s[self.pos + 1] == b'*' {
                self.pos += 2;
                while self.pos + 1 < self.s.len()
                    && !(self.s[self.pos] == b'*' && self.s[self.pos + 1] == b'/')
                {
                    self.pos += 1;
                }
                self.pos = (self.pos + 2).min(self.s.len());
            } else {
                break;
            }
        }
    }

    fn peek(&self) -> Option<u8> {
        self.s.get(self.pos).copied()
    }

    fn consume_group(&mut self) {
        // 假定 self.s[self.pos] == '('
        let mut depth = 0i32;
        while self.pos < self.s.len() {
            let c = self.s[self.pos];
            self.pos += 1;
            if c == b'(' {
                depth += 1;
            } else if c == b')' {
                depth -= 1;
                if depth == 0 {
                    return;
                }
            }
        }
    }

    fn next_token(&mut self) -> Option<String> {
        self.skip_ws();
        if self.pos >= self.s.len() {
            return None;
        }
        let start = self.pos;
        let b = self.s[self.pos];
        if b == b'{' || b == b'}' || b == b';' {
            self.pos += 1;
            return Some((b as char).to_string());
        }
        if b == b'(' {
            self.consume_group();
            return Some(String::from_utf8_lossy(&self.s[start..self.pos]).into_owned());
        }
        // 词元：读至空白/结构符；附着在词元上的括号组整体吞掉（如 div(phi,U)、grad(U)）
        while self.pos < self.s.len() {
            let c = self.s[self.pos];
            if c.is_ascii_whitespace() || c == b'{' || c == b'}' || c == b';' {
                break;
            }
            if c == b'(' {
                self.consume_group();
                continue;
            }
            if c == b')' {
                break;
            }
            self.pos += 1;
        }
        Some(String::from_utf8_lossy(&self.s[start..self.pos]).into_owned())
    }
}

fn parse_dict(lx: &mut Lexer) -> Result<Dict, String> {
    let mut d: Dict = Vec::new();
    loop {
        lx.skip_ws();
        match lx.peek() {
            None => return Ok(d),
            Some(b'}') => {
                lx.pos += 1;
                return Ok(d);
            }
            Some(b';') => {
                lx.pos += 1;
                continue;
            }
            _ => {}
        }
        let key = lx.next_token().ok_or("字典键处意外 EOF")?;
        lx.skip_ws();
        match lx.peek() {
            Some(b'{') => {
                lx.pos += 1;
                let sub = parse_dict(lx)?;
                d.push((key, Entry::Sub(sub)));
            }
            _ => {
                let mut parts: Vec<String> = Vec::new();
                loop {
                    lx.skip_ws();
                    match lx.peek() {
                        Some(b';') => {
                            lx.pos += 1;
                            break;
                        }
                        None => break,
                        Some(b'}') => break,
                        _ => parts.push(lx.next_token().ok_or("value 处意外 EOF")?),
                    }
                }
                d.push((key, Entry::Word(parts.join(" "))));
            }
        }
    }
}

/// 解析 OpenFOAM ascii FoamFile 字典（忽略头部 FoamFile{} 元信息）
pub fn parse_foam_bytes(bytes: &[u8]) -> Result<Dict, String> {
    let mut lx = Lexer::new(bytes);
    parse_dict(&mut lx)
}

pub fn parse_foam_file(path: &Path) -> Result<Dict, String> {
    let bytes = fs::read(path).map_err(|e| format!("读取 {} 失败: {e}", path.display()))?;
    parse_foam_bytes(&bytes)
}

/// 定位 ascii 列表文件（points/faces/owner/neighbour）的数据体：
/// 返回 (count, 数据行迭代器)。数据体 = 第一个独立 '(' 行到 ')' 行之间。
pub fn list_body(text: &str) -> Result<(usize, impl Iterator<Item = &str>), String> {
    let mut it = text.lines();
    let mut prev: Option<&str> = None;
    let count;
    loop {
        let l = it.next().ok_or("未找到列表起始 '(' 行")?;
        let t = l.trim();
        if t.is_empty() {
            continue;
        }
        if t == "(" {
            count = prev
                .ok_or("'(' 行前无计数行")?
                .trim()
                .parse::<usize>()
                .map_err(|e| format!("计数行解析失败: {e}"))?;
            break;
        }
        prev = Some(t);
    }
    Ok((count, it.take_while(|l| l.trim() != ")")))
}

/// 解析一行 face："4(121551 121660 121661 121552)" → [121551, 121660, 121661, 121552]
fn parse_face_line(line: &str) -> Result<Vec<u32>, String> {
    let b = line.as_bytes();
    let mut i = 0usize;
    while i < b.len() && b[i] != b'(' {
        i += 1;
    }
    if i >= b.len() {
        return Err(format!("face 行无 '(': {line}"));
    }
    i += 1;
    let mut v: Vec<u32> = Vec::new();
    while i < b.len() && b[i] != b')' {
        while i < b.len() && (b[i] == b' ' || b[i] == b'\t') {
            i += 1;
        }
        let start = i;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
        }
        if i > start {
            v.push(
                line[start..i]
                    .parse::<u32>()
                    .map_err(|e| format!("face 标签解析失败: {e}"))?,
            );
        } else {
            break;
        }
    }
    Ok(v)
}

/// polyMesh 原始数据（扁平 CSR 存储，避免 Vec<Vec<u32>> 的大量小分配）
pub struct RawPolyMesh {
    pub points: Vec<[f64; 3]>,
    pub face_nodes: Vec<u32>,
    pub face_start: Vec<u32>,
    pub face_owner: Vec<u32>,
    pub face_neigh: Vec<u32>, // 仅内部面
    pub patches: Vec<Patch>,
}

/// 读取 polyMesh/boundary（polyBoundaryMesh 列表格式，非普通 FoamFile 字典）：
/// `FoamFile{...} <n> ( <name> { type; nFaces; startFace; } ... )`
fn read_boundary(path: &Path) -> Result<Vec<Patch>, String> {
    let bytes = fs::read(path).map_err(|e| format!("读取 {} 失败: {e}", path.display()))?;
    let mut lx = Lexer::new(&bytes);
    // 跳过 FoamFile{...} 头（至第一个 '}'）
    loop {
        let t = lx.next_token().ok_or("boundary: 无 FoamFile 头")?;
        if t == "}" {
            break;
        }
    }
    // 字节级定位列表起始 '('（计数行之前可能有多个 token，逐个跳过）
    loop {
        lx.skip_ws();
        match lx.peek() {
            Some(b'(') => {
                lx.pos += 1;
                break;
            }
            Some(_) => {
                lx.next_token();
            }
            None => return Err("boundary: 未找到列表 '('".into()),
        }
    }
    let mut patches: Vec<Patch> = Vec::new();
    loop {
        lx.skip_ws();
        if lx.peek() == Some(b')') {
            break;
        }
        let name = lx.next_token().ok_or("boundary 列表意外 EOF")?;
        if name == "{" || name == "}" || name == ";" {
            return Err(format!("boundary: 意外的结构符 '{name}'"));
        }
        let open = lx.next_token().ok_or("boundary: patch 名后缺 '{'")?;
        if open != "{" {
            return Err(format!(
                "boundary: patch {name} 后期望 '{{'，得到 '{open}'"
            ));
        }
        let sub = parse_dict(&mut lx)?;
        let ptype = dict_get(&sub, "type")?.word()?.to_string();
        let n = dict_get(&sub, "nFaces")?.usize()?;
        let start = dict_get(&sub, "startFace")?.usize()?;
        patches.push(Patch {
            name,
            ptype,
            start,
            n_faces: n,
        });
    }
    Ok(patches)
}

/// 读取 OpenFOAM ascii polyMesh 目录
pub fn read_polymesh(dir: &Path) -> Result<RawPolyMesh, String> {
    let read = |name: &str| -> Result<String, String> {
        fs::read_to_string(dir.join(name))
            .map_err(|e| format!("读取 {}/{} 失败: {e}", dir.display(), name))
    };
    // points
    let pts_text = read("points")?;
    let (n_pts, lines) = list_body(&pts_text)?;
    let mut points: Vec<[f64; 3]> = Vec::with_capacity(n_pts);
    for (i, l) in lines.enumerate() {
        let inner = l
            .trim()
            .strip_prefix('(')
            .and_then(|s| s.strip_suffix(')'))
            .ok_or_else(|| format!("points 第 {i} 行格式错误: {l}"))?;
        let nums: Result<Vec<f64>, _> =
            inner.split_whitespace().map(|t| t.parse::<f64>()).collect();
        let nums = nums.map_err(|e| format!("points 第 {i} 行: {e}"))?;
        if nums.len() != 3 {
            return Err(format!("points 第 {i} 行分量数 {}", nums.len()));
        }
        points.push([nums[0], nums[1], nums[2]]);
    }
    if points.len() != n_pts {
        return Err(format!(
            "points 计数不符：声明 {n_pts} 实际 {}",
            points.len()
        ));
    }
    // faces
    let fc_text = read("faces")?;
    let (n_faces, lines) = list_body(&fc_text)?;
    let mut face_nodes: Vec<u32> = Vec::with_capacity(n_faces * 4);
    let mut face_start: Vec<u32> = Vec::with_capacity(n_faces + 1);
    face_start.push(0);
    for (i, l) in lines.enumerate() {
        let v = parse_face_line(l).map_err(|e| format!("faces 第 {i} 行: {e}"))?;
        if v.len() < 3 {
            return Err(format!("faces 第 {i} 行节点数 {} < 3", v.len()));
        }
        for &x in &v {
            if x as usize >= points.len() {
                return Err(format!("faces 第 {i} 行节点号 {x} 越界"));
            }
        }
        face_nodes.extend_from_slice(&v);
        face_start.push(face_nodes.len() as u32);
    }
    if face_start.len() != n_faces + 1 {
        return Err(format!(
            "faces 计数不符：声明 {n_faces} 实际 {}",
            face_start.len() - 1
        ));
    }
    // owner
    let ow_text = read("owner")?;
    let (n_own, lines) = list_body(&ow_text)?;
    let mut face_owner: Vec<u32> = Vec::with_capacity(n_own);
    for (i, l) in lines.enumerate() {
        let t = l.trim();
        if t.is_empty() {
            continue;
        }
        face_owner.push(
            t.parse::<u32>()
                .map_err(|e| format!("owner 第 {i} 行 '{t}': {e}"))?,
        );
    }
    if face_owner.len() != n_faces {
        return Err(format!(
            "owner 计数 {} 与 faces 计数 {} 不符",
            face_owner.len(),
            n_faces
        ));
    }
    // neighbour（仅内部面）
    let nb_text = read("neighbour")?;
    let (n_int, lines) = list_body(&nb_text)?;
    let mut face_neigh: Vec<u32> = Vec::with_capacity(n_int);
    for (i, l) in lines.enumerate() {
        let t = l.trim();
        if t.is_empty() {
            continue;
        }
        face_neigh.push(
            t.parse::<u32>()
                .map_err(|e| format!("neighbour 第 {i} 行 '{t}': {e}"))?,
        );
    }
    if face_neigh.len() != n_int {
        return Err(format!(
            "neighbour 计数不符：声明 {n_int} 实际 {}",
            face_neigh.len()
        ));
    }
    if n_int > n_faces {
        return Err(format!("内部面 {n_int} > 总面 {n_faces}"));
    }
    // boundary（polyBoundaryMesh 列表格式：FoamFile{...} n ( name { type; nFaces; startFace; } ... )）
    let patches = read_boundary(&dir.join("boundary"))?;
    // 校验 patch 平铺 [n_internal, n_faces)
    let mut expect = n_int;
    for p in &patches {
        if p.start != expect {
            return Err(format!(
                "patch {} startFace {} != 期望 {}",
                p.name, p.start, expect
            ));
        }
        expect += p.n_faces;
    }
    if expect != n_faces {
        return Err(format!(
            "patch 面数合计 {expect} != 总面数 {n_faces}（边界面 {}）",
            n_faces - n_int
        ));
    }
    Ok(RawPolyMesh {
        points,
        face_nodes,
        face_start,
        face_owner,
        face_neigh,
        patches,
    })
}

/// 便捷：读目录并构建带几何量的 Mesh
pub fn load_mesh(case_dir: &Path) -> Result<Mesh, String> {
    let pm_dir = case_dir.join("constant").join("polyMesh");
    let raw = read_polymesh(&pm_dir)?;
    Mesh::build(
        raw.points,
        raw.face_nodes,
        raw.face_start,
        raw.face_owner,
        raw.face_neigh,
        raw.patches,
    )
}
