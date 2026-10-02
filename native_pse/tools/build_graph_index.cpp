// Standalone finite S7 orbit-index generator. C++17, no external libraries.
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

static unsigned edge(unsigned a,unsigned b){if(a>b)std::swap(a,b);return b*(b-1)/2+a;}
static uint32_t key(uint32_t g){uint32_t k=0;for(unsigned a=0;a<7;++a)for(unsigned b=a+1;b<7;++b)k=(k<<1)|((g>>edge(a,b))&1);return k;}
template<class T> static void save(const std::filesystem::path& p,const std::vector<T>& data){
    std::ofstream out(p,std::ios::binary);if(!out)throw std::runtime_error("open output");
    for(T value:data)for(unsigned b=0;b<sizeof(T);++b)out.put(char((value>>(8*b))&255));
    if(!out)throw std::runtime_error("write output");
}
int main(int argc,char**argv){try{
    if(argc!=2)throw std::runtime_error("usage: build_graph_index OUTPUT_DIRECTORY");
    constexpr uint32_t N=1u<<21;
    std::array<unsigned,7> p={0,1,2,3,4,5,6};
    std::vector<std::array<unsigned,21>> maps;std::vector<uint32_t> codes;
    do{
        std::array<unsigned,21> m{};uint32_t code=0;
        for(unsigned i=0;i<7;++i)code|=p[i]<<(3*i);
        for(unsigned j=1;j<7;++j)for(unsigned i=0;i<j;++i)m[edge(i,j)]=edge(p[i],p[j]);
        maps.push_back(m);codes.push_back(code);
    }while(std::next_permutation(p.begin(),p.end()));
    if(maps.size()!=5040)throw std::runtime_error("permutations");
    std::vector<uint16_t> ids(N,UINT16_MAX);std::vector<uint32_t>witness(N,0),meta;
    for(uint32_t g=0;g<N;++g){if(ids[g]!=UINT16_MAX)continue;
        const uint32_t cls=meta.size()/4;if(cls>=UINT16_MAX)throw std::runtime_error("class overflow");
        uint32_t minimum=UINT32_MAX,canonical=0,count=0;
        for(size_t q=0;q<maps.size();++q){uint32_t image=0;
            for(unsigned e=0;e<21;++e)if((g>>e)&1)image|=1u<<maps[q][e];
            uint32_t k=key(image);if(k<minimum){minimum=k;canonical=image;}
            if(ids[image]==UINT16_MAX){ids[image]=uint16_t(cls);witness[image]=codes[q];++count;}
            else if(ids[image]!=cls)throw std::runtime_error("overlapping classes");
        }
        if(!count||5040%count)throw std::runtime_error("orbit size");
        meta.insert(meta.end(),{g,canonical,count,5040/count});
    }
    const std::filesystem::path dir(argv[1]);std::filesystem::create_directories(dir);
    save(dir/"s7_classes.bin",ids);save(dir/"s7_metadata.bin",meta);save(dir/"s7_witnesses.bin",witness);
    std::cout<<"{\"graphs\":"<<N<<",\"classes\":"<<meta.size()/4<<",\"runtime_bytes\":"<<2*N+4*meta.size()<<",\"witness_bytes\":"<<4*N<<"}\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
