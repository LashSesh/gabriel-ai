// Independent matrix-action checker. Does not reuse the generator's bit maps.
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

using Matrix=std::array<std::array<unsigned char,7>,7>;
static void require(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
static std::vector<unsigned char>read(const std::filesystem::path&p){std::ifstream f(p,std::ios::binary);require(bool(f),"open input");return {std::istreambuf_iterator<char>(f),{}};}
static uint32_t u32(const std::vector<unsigned char>&b,size_t n){return uint32_t(b.at(n))|(uint32_t(b.at(n+1))<<8)|(uint32_t(b.at(n+2))<<16)|(uint32_t(b.at(n+3))<<24);}
static Matrix matrix(uint32_t bits){Matrix a{};unsigned e=0;for(unsigned col=1;col<7;++col)for(unsigned row=0;row<col;++row,++e)a[row][col]=a[col][row]=(bits>>e)&1;return a;}
static uint32_t bits(const Matrix&a){unsigned e=0;uint32_t out=0;for(unsigned col=1;col<7;++col)for(unsigned row=0;row<col;++row,++e)out|=uint32_t(a[row][col])<<e;return out;}
static uint32_t key(const Matrix&a){uint32_t out=0;for(unsigned row=0;row<7;++row)for(unsigned col=row+1;col<7;++col)out=(out<<1)|a[row][col];return out;}
int main(int argc,char**argv){try{
    require(argc==2,"usage: verify_graph_index DIRECTORY");constexpr uint32_t N=1u<<21;
    std::filesystem::path dir(argv[1]);auto ids=read(dir/"s7_classes.bin"),meta=read(dir/"s7_metadata.bin"),witness=read(dir/"s7_witnesses.bin");
    require(ids.size()==2*N&&witness.size()==4*N,"table length");
    require(!meta.empty()&&meta.size()%16==0,"metadata length");const size_t K=meta.size()/16;
    auto cls=[&](uint32_t g){return unsigned(ids[2*g])|(unsigned(ids[2*g+1])<<8);};
    std::vector<Matrix> reps;std::vector<uint32_t>counts(K,0),minima(K,UINT32_MAX),canon(K,0);
    for(size_t k=0;k<K;++k){uint32_t r=u32(meta,16*k);require(r<N,"representative range");reps.push_back(matrix(r));}
    uint64_t closures=0;
    for(uint32_t g=0;g<N;++g){unsigned c=cls(g);require(c<K,"class range");
        uint32_t code=u32(witness,4*g);require((code>>21)==0,"witness high bits");
        std::array<unsigned,7> inv{};unsigned mask=0;
        for(unsigned i=0;i<7;++i){unsigned x=(code>>(3*i))&7;require(x<7&&!(mask&(1u<<x)),"witness bijection");mask|=1u<<x;inv[x]=i;}
        Matrix a=matrix(g);
        for(unsigned i=0;i<7;++i)for(unsigned j=0;j<7;++j)require(a[i][j]==reps[c][inv[i]][inv[j]],"witness image");
        ++counts[c];uint32_t order=key(a);if(order<minima[c]){minima[c]=order;canon[c]=g;}
        for(unsigned t=0;t<6;++t){Matrix changed=a;std::swap(changed[t],changed[t+1]);
            for(unsigned row=0;row<7;++row)std::swap(changed[row][t],changed[row][t+1]);
            require(cls(bits(changed))==c,"generator closure");++closures;
        }
    }
    for(size_t k=0;k<K;++k){require(counts[k]>0&&5040%counts[k]==0,"nonempty orbit cardinality");
        require(u32(meta,16*k+4)==canon[k],"canonical minimum");
        require(u32(meta,16*k+8)==counts[k],"orbit cardinality metadata");
        require(u32(meta,16*k+12)==5040/counts[k],"stabilizer metadata");}
    std::cout<<"{\"status\":\"passed\",\"graphs\":"<<N<<",\"classes\":"<<K<<",\"witness_checks\":"<<N<<",\"generator_closure_checks\":"<<closures<<",\"minimum_checks\":"<<K<<"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
